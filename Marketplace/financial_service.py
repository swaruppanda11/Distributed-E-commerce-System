import random
import argparse
from spyne import Application, ServiceBase, Unicode, Boolean, rpc
from spyne.protocol.soap import Soap11
from spyne.server.wsgi import WsgiApplication
from wsgiref.simple_server import make_server


class FinancialTransactionService(ServiceBase):
    @rpc(Unicode, Unicode, Unicode, Unicode, _returns=Boolean)
    def ProcessPayment(ctx, name, card_number, expiration_date, security_code):
        if not card_number or len(card_number.replace(' ', '')) < 12:
            return False
        return random.random() < 0.9


application = Application(
    [FinancialTransactionService],
    tns='financial.service',
    in_protocol=Soap11(validator='lxml'),
    out_protocol=Soap11()
)

wsgi_app = WsgiApplication(application)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Financial Transaction SOAP Service')
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--port', type=int, default=8000)
    args = parser.parse_args()

    server = make_server(args.host, args.port, wsgi_app)
    print(f'Financial Service SOAP server on {args.host}:{args.port}')
    print(f'WSDL available at http://{args.host}:{args.port}/?wsdl')
    server.serve_forever()
