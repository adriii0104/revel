from odoo import models, fields, api
import logging
from datetime import datetime
from escpos.printer import Network
import smtplib
from email.mime.text import MIMEText

_logger = logging.getLogger(__name__)

class PosConfig(models.Model):
    _inherit = 'pos.config'

    def action_print_totals_kanban(self):
        # Initialize variables
        totals_by_waiter = {}
        product_details = {}
        category_totals = {}
        total_company_sales = 0
        total_payment_methods = {}
        payment_counts = {}  # To track the number of payments per method
        total_itbis = 0
        initial_balance = 0
        final_balance = 0

        # User who requested the report and current date
        user = self.env.user
        current_date = datetime.now().strftime('%Y-%m-%d')

        # Get the current session
        current_session = self.current_session_id
        
        # If there is no current session, get the last closed session
        if not current_session or current_session.state != 'opened':
            current_session = self.env['pos.session'].search(
                [('config_id', '=', self.id), ('state', '=', 'closed')], 
                order='stop_at desc', limit=1
            )
        
        if not current_session:
            _logger.warning("No current or past sessions found.")
            return  # No session to process
        
        # Get the initial balance
        initial_balance = current_session.cash_register_balance_start or 0

        # Get the orders of the session
        orders = self.env['pos.order'].search([('session_id', '=', current_session.id)])

        # Iterate through orders
        for order in orders:
            waiter = order.user_id
            if waiter not in totals_by_waiter:
                totals_by_waiter[waiter] = {
                    'total_sales': 0, 'payment_methods': {}, 'total_operations': 0,
                    'products': {}, 'cancelled': 0, 'product_units_sold': 0
                }

            total_itbis += order.amount_tax

            for line in order.lines:
                product_name = line.product_id.name
                category_name = line.product_id.categ_id.name

                # Update product details
                totals_by_waiter[waiter]['products'].setdefault(product_name, {'quantity': 0, 'total': 0})
                totals_by_waiter[waiter]['products'][product_name]['quantity'] += line.qty
                totals_by_waiter[waiter]['products'][product_name]['total'] += line.price_subtotal_incl

                # General product details
                product_details.setdefault(product_name, {'quantity': 0, 'total': 0})
                product_details[product_name]['quantity'] += line.qty
                product_details[product_name]['total'] += line.price_subtotal_incl

                # Update category totals
                category_totals.setdefault(category_name, {'quantity': 0, 'total': 0})
                category_totals[category_name]['quantity'] += line.qty
                category_totals[category_name]['total'] += line.price_subtotal_incl

                # Update total units sold by waiter
                totals_by_waiter[waiter]['product_units_sold'] += line.qty

            for payment in order.payment_ids:
                payment_method = payment.payment_method_id.name
                totals_by_waiter[waiter]['payment_methods'].setdefault(payment_method, 0)
                totals_by_waiter[waiter]['payment_methods'][payment_method] += payment.amount
                totals_by_waiter[waiter]['total_sales'] += payment.amount
                totals_by_waiter[waiter]['total_operations'] += 1
                total_company_sales += payment.amount
                total_payment_methods.setdefault(payment_method, 0)
                total_payment_methods[payment_method] += payment.amount
                payment_counts.setdefault(payment_method, 0)
                payment_counts[payment_method] += 1

            # Update the final balance
            final_balance += order.amount_total

            # Track cancellations based on the state field
            if order.state == 'cancel':
                totals_by_waiter[waiter]['cancelled'] += order.amount_total

        # ESC/POS formatting
        bold_on = chr(27) + chr(69) + chr(1)
        bold_off = chr(27) + chr(69) + chr(0)

        # Format the ticket text
        ticket_text = f"""
----------------------------------------
        REVEL BAR & KITCHEN
----------------------------------------
Solicitado por: {user.name}
Fecha del Reporte: {current_date}


----------------------------------------
SALDO INICIAL:                 ${initial_balance:.2f}
----------------------------------------

Pagos Registrados:
"""
        for method, amount in total_payment_methods.items():
            count = payment_counts.get(method, 0)
            ticket_text += f"{method:<20} Cantidad: {count:<4} ${amount:,.2f}\n"

        ticket_text += f"""
----------------------------------------
SALDO FINAL:                   ${final_balance:.2f}
----------------------------------------

Total Ventas: ${total_company_sales:.2f}
Total ITBIS: ${total_itbis:.2f}
----------------------------------------
"""

        # Product details
        ticket_text += "DETALLE DE PRODUCTOS VENDIDOS:\n"
        ticket_text += "{:<15} {:<10} {:<10}\n".format("Nombre", "Cant", "Total")
        for product, details in product_details.items():
            ticket_text += "{:<15} {:<10.1f} ${:<10.2f}\n".format(product[:30], details['quantity'], details['total'])

        ticket_text += "\n----------------------------------------\n"

        # Product category totals
        ticket_text += "{}DETALLE DE CATEGORÍAS DE PRODUCTOS VENDIDOS:{}\n".format(bold_on, bold_off)
        ticket_text += "{:<13} {:<10} {:<10}\n".format("Categoría", "Cant", "Total")
        for category, details in category_totals.items():
            ticket_text += "{}{:<13} {:<10.1f} ${:<10.2f}{}\n".format(bold_on, category[:30], details['quantity'], details['total'], bold_off)
        
        ticket_text += "\n----------------------------------------\n"

        # Payments by User (receipt format)
        ticket_text += "COBROS POR USUARIO:\n"
        ticket_text += "----------------------------------------\n"
        for waiter, data in totals_by_waiter.items():
            ticket_text += f"{bold_on}{waiter.name}{bold_off}\n"
            for payment_method, amount in data['payment_methods'].items():
                ticket_text += "{}    {:<10} {:<5} ${:<10.2f}\n".format(bold_on,
                    payment_method[:10],
                    data['total_operations'],
                    amount,
                )
            ticket_text += "{}    Total {:<10} ${:<10.2f} {}\n".format(bold_on,
                data['total_operations'],
                data['total_sales'],
                bold_off
            )

        # New section: Summary by User
        ticket_text += "----------------------------------------\n"
        ticket_text += "RESUMEN POR USUARIO:\n"
        ticket_text += "{:<20} {:<10} {:<10} {:<10}\n".format("Usuario", "Cancelados", "Ventas", "Total")
        for waiter, data in totals_by_waiter.items():
            ticket_text += "{:<20} ${:<10.2f} {:<10} ${:<10.2f}\n".format(
                waiter.name,
                data['cancelled'],
                data['product_units_sold'],
                data['total_sales']
            )

        # End of report
        ticket_text += "----------------------------------------\n"
        ticket_text += "          FIN DEL INFORME\n"
        ticket_text += "----------------------------------------"

        # Print the ticket
        print(ticket_text)
        printer_ip = '192.168.100.110'
        printer_port = 9100
        printer = Network(printer_ip, printer_port)
        printer.text(ticket_text)
        printer.cut()
        printer.close()
        email_content = f"""
----------------------------------------
        REVEL BAR & KITCHEN
----------------------------------------
Solicitado por: {user.name}
Fecha del Reporte: {current_date}

----------------------------------------
SALDO INICIAL:                 ${initial_balance:.2f}
SALDO FINAL:                   ${final_balance:.2f}
----------------------------------------

Total Ventas: ${total_company_sales:.2f}
Total ITBIS: ${total_itbis:.2f}
----------------------------------------

RESUMEN POR USUARIO:
----------------------------------------
"""
        email_content += "{:<20} {:<10} {:<10} {:<10}\n".format("Usuario", "Cancelados", "Ventas", "Total")
        for waiter, data in totals_by_waiter.items():
            email_content += "{:<20} ${:<10.2f} {:<10} ${:<10.2f}\n".format(
                waiter.name,
                data['cancelled'],
                data['product_units_sold'],
                data['total_sales']
            )

        email_content += "----------------------------------------\n"

        # Send the email report
        report_sales(email_content)

def report_sales(body_rec):
    # Email details
    sender_email = "reportsendrevel@outlook.com"
    receiver_email = "adriii0104@hotmail.com"
    subject = "Reporte de ventas"
    body = body_rec
    password = "revelbar2023"

    # Create MIMEText object (plain text email)
    msg = MIMEText(body, "plain")
    msg["Subject"] = subject
    msg["From"] = sender_email
    msg["To"] = receiver_email

    # Sending the email using SMTP
    try:
        # Connect to the SMTP server for Outlook
        with smtplib.SMTP("smtp-mail.outlook.com", 587) as server:  # Use port 587 for TLS
            server.starttls()  # Upgrade the connection to secure using TLS
            server.login(sender_email, password)
            server.sendmail(sender_email, receiver_email, msg.as_string())
        print("Email sent successfully!")
    except Exception as e:
        print(f"Error sending email: {e}")
