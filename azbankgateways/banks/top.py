import logging
from json import dumps, loads
from time import gmtime, strftime

from django.utils.translation import gettext_lazy as _
from zeep import Client, Transport

from azbankgateways.banks import BaseBank
from azbankgateways.exceptions import SettingDoesNotExist
from azbankgateways.exceptions.exceptions import BankGatewayRejectPayment
from azbankgateways.models import BankType, CurrencyEnum, PaymentStatus


class Top(BaseBank):
    _terminal_code = None
    _username = None
    _password = None

    def __init__(self, **kwargs):
        super(Top, self).__init__(**kwargs)
        self.set_gateway_currency(CurrencyEnum.IRR)
        self._payment_url = "https://pec.shaparak.ir/NewIPG/"

    def get_bank_type(self):
        return BankType.TOP

    def set_default_settings(self):
        for item in ["TERMINAL_CODE", "USERNAME", "PASSWORD"]:
            if item not in self.default_setting_kwargs:
                raise SettingDoesNotExist()
            setattr(self, f"_{item.lower()}", self.default_setting_kwargs[item])

    """
    gateway
    """

    @classmethod
    def get_minimum_amount(cls):
        return 1000

    def _get_gateway_payment_url_parameter(self):
        return self._payment_url

    def _get_gateway_payment_parameter(self):
        params = {
            "RefId": self.get_reference_number(),
            "MobileNo": self.get_mobile_number(),
        }
        return params

    def _get_gateway_payment_method_parameter(self):
        return "POST"

    """
    pay
    """

    def get_pay_data(self):
        description = "خرید با شماره پیگیری - {}".format(self.get_tracking_code())
        data = {
            "LoginAccount": self._password,
            "orderId": int(self.get_tracking_code()),
            "Amount": int(self.get_gateway_amount()),
            "CallBackUrl": self._get_gateway_callback_url(),
            "AdditionalData": description,
            "Originator": self.get_mobile_number(),
        }
        return data

    def prepare_pay(self):
        super(Top, self).prepare_pay()

    def pay(self):
        super(Top, self).pay()

        data = self.get_pay_data()
        client = self._get_client()
        response = client.service.SalePayment(**data)
        try:
            status, token = response.split(",")
            if status == "0":
                self._set_reference_number(token)
        except ValueError:
            status_text = self._get_status_text(response=response)
            self._set_transaction_status_text(status_text)
            logging.critical(status_text)
            raise BankGatewayRejectPayment(self.get_transaction_status_text())

    """
    verify from gateway
    """

    def prepare_verify_from_gateway(self):
        super(Top, self).prepare_verify_from_gateway()
        post = self.get_request().POST
        token = post.get("RefId")
        if not token:
            return
        self._set_reference_number(token)
        self._set_bank_record()
        self._bank.extra_information = dumps(dict(post.items()))
        self._bank.save()

    def verify_from_gateway(self, request):
        super(Top, self).verify_from_gateway(request)

    """
    verify
    """

    def get_verify_data(self):
        super(Top, self).get_verify_data()
        data = {
            "terminalId": self._terminal_code,
            "userName": self._username,
            "userPassword": self._password,
            "orderId": self.get_tracking_code(),
            "saleOrderId": self.get_tracking_code(),
            "saleReferenceId": self._get_sale_reference_id(),
        }
        return data

    def prepare_verify(self, tracking_code):
        super(Top, self).prepare_verify(tracking_code)

    def verify(self, transaction_code):
        super(Top, self).verify(transaction_code)
        data = self.get_verify_data()
        client = self._get_client()

        verify_result = client.service.bpVerifyRequest(**data)
        if verify_result == "0":
            self._settle_transaction()
        else:
            verify_result = client.service.bpInquiryRequest(**data)
            if verify_result == "0":
                self._settle_transaction()
            else:
                logging.debug("Not able to verify the transaction, Making reversal request")
                reversal_result = client.service.bpReversalRequest(**data)

                if reversal_result != "0":
                    logging.debug("Reversal request was not successfull")

                self._set_payment_status(PaymentStatus.CANCEL_BY_USER)
                logging.debug("Top gateway unapproved the payment")

    def _settle_transaction(self):
        data = self.get_verify_data()
        client = self._get_client()
        settle_result = client.service.bpSettleRequest(**data)
        if settle_result == "0":
            self._set_payment_status(PaymentStatus.COMPLETE)
        else:
            logging.debug("Top gateway did not settle the payment")

    @staticmethod
    def _get_client():
        transport = Transport(timeout=5, operation_timeout=5)
        client = Client(
            "https://pec.shaparak.ir/NewIPGServices/Sale/SaleService.asmx?wsdl", transport=transport
        )
        return client

    @staticmethod
    def _get_current_time():
        return strftime("%H%M%S")

    @staticmethod
    def _get_current_date():
        return strftime("%Y%m%d", gmtime())

    @staticmethod
    def _get_status_text(response):
        status_text = {
            "-1552": _("Payment Request Is Not Eligible To Reversal"),
            "-1551": _("Payment Request Is Already Reversed"),
            "-1550": _("Payment Request Status Is Not Reversible"),
            "-1549": _("Max Allowed Time To Reversal Has Exceeded"),
            "-1548": _("Bill Payment Request Service Failed"),
            "-1540": _("Invalid Confirm Request Service"),
            "-1536": _("Topup Charge Service Topup Charge Request Failed"),
            "-1533": _("Payment Is Already Confirmed"),
            "-1532": _("Merchant Has Confirmed Payment Request"),
            "-1531": _("Cannot Confirm NonSuccessful Payment"),
            "-1530": _("Merchant Confirm Payment Request Access Violated"),
            "-1528": _("Confirm Payment Request Info Not Found"),
            "-1527": _("Call Sale Payment Request Service Failed"),
            "-1507": _("Reversal Completed"),
            "-1505": _("Payment Confirm Requested"),
            "-138": _("Canceled By User"),
            "-132": _("Invalid Minimum Payment Amount"),
            "-131": _("Invalid Token"),
            "-130": _("Token Is Expired"),
            "-128": _("Invalid Ip Address Format"),
            "-127": _("Invalid Merchant Ip"),
            "-126": _("Invalid Merchant Pin"),
            "-121": _("Invalid String Is Numeric"),
            "-120": _("Invalid Length"),
            "-119": _("Invalid Organization Id"),
            "-118": _("Value Is Not Numeric"),
            "-117": _("Length Is Less Of Minimum"),
            "-116": _("Length Is More Of Maximum"),
            "-115": _("Invalid Pay Id"),
            "-114": _("Invalid Bill Id"),
            "-113": _("Value Is Null"),
            "-112": _("Order Id Duplicated"),
            "-111": _("Invalid Merchant Max Trans Amount"),
            "-108": _("Reverse Is Not Enabled"),
            "-107": _("Advice Is Not Enabled"),
            "-106": _("Charge Is Not Enabled"),
            "-105": _("Topup Is Not Enabled"),
            "-104": _("Bill Is Not Enabled"),
            "-103": _("Sale Is Not Enabled"),
            "-102": _("Reverse Successful"),
            "-101": _("Merchant Authentication Failed"),
            "-100": _("Merchant Is Not Active"),
            "-1": _("Server Error"),
            "0": _("Successful"),
            "1": _("Refer To Card Issuer Decline"),
            "2": _("Refer To Card Issuer Special Conditions"),
            "3": _("Invalid Merchant"),
            "5": _("Do Not Honour"),
            "6": _("Error"),
            "8": _("Honour With Identification"),
            "9": _("Request In Progress"),
            "10": _("Approved For Partial Amount"),
            "12": _("Invalid Transaction"),
            "13": _("Invalid Amount"),
            "14": _("Invalid Card Number"),
            "15": _("No Such Issuer"),
            "17": _("Customer Cancellation"),
            "20": _("Invalid Response"),
            "21": _("No Action Taken"),
            "22": _("Suspected Malfunction"),
            "30": _("Format Error"),
            "31": _("Bank Not Supported By Switch"),
            "32": _("Completed Partially"),
            "33": _("Expired Card Pick Up"),
            "38": _("Allowable PIN Tries Exceeded Pick Up"),
            "39": _("No Credit Account"),
            "40": _("Requested Function is not Supported"),
            "41": _("Lost Card"),
            "43": _("Stolen Card"),
            "45": _("Bill Can not Be Payed"),
            "51": _("No Sufficient Funds"),
            "54": _("Expired Account"),
            "55": _("Incorrect PIN"),
            "56": _("No Card Record"),
            "57": _("Transaction Not Permitted To CardHolder"),
            "58": _("Transaction Not Permitted To Terminal"),
            "59": _("Suspected Fraud-Decline"),
            "61": _("Exceeds Withdrawal Amount Limit"),
            "62": _("Restricted Card-Decline"),
            "63": _("Security Violation"),
            "65": _("Exceeds Withdrawal Frequency Limit"),
            "68": _("Response Received Too Late"),
            "69": _("Allowable Number Of PIN Tries Exceeded"),
            "75": _("PIN Reties Exceeds-Slm"),
            "78": _("Deactivated Card-Slm"),
            "79": _("Invalid Amount-Slm"),
            "80": _("Transaction Denied-Slm"),
            "81": _("Cancelled Card-Slm"),
            "83": _("Host Refuse-Slm"),
            "84": _("Issuer Down-Slm"),
            "91": _("Issuer Or Switch Is Inoperative"),
            "92": _("Financial Inst Or Intermediate Net Facility Not Found for Routing"),
            "93": _("Transaction Cannot Be Completed"),
        }

        return status_text.get(response, _("Unknown error"))

    def _get_sale_reference_id(self):
        extra_information = loads(getattr(self._bank, "extra_information", "{}"))
        return extra_information.get("SaleReferenceId", "1")
