import smtplib
from email.message import EmailMessage
from django.conf import settings
from django.utils import timezone

import random, string, datetime, time
from django.forms.models import model_to_dict
import hashlib

from .models import Voters, PoliticalParty, Vote, Block, VoteBackup, MiningInfo
from .merkle_tool import MerkleTools

from Crypto.Hash import SHA3_256
from Crypto.PublicKey import ECC
from Crypto.Signature import DSS

EMAIL_ADDRESS = settings.EMAIL_ADDRESS
EMAIL_PASSWORD = settings.EMAIL_PASSWORD

# NEW FEATURE: Phone OTP Verification - Twilio SMS Service
try:
    from twilio.rest import Client
    TWILIO_AVAILABLE = True
except ImportError:
    TWILIO_AVAILABLE = False

# def send_email_otp(email_to):
#     otp = ''.join(random.choice(string.ascii_lowercase + string.ascii_uppercase + string.digits) for _ in range(8))
#     msg = EmailMessage()
#     msg['From'] = EMAIL_ADDRESS
#     msg['To'] = email_to
#     msg['Subject'] = 'Don\'t reply, OTP for email verfication'
#     content = 'Verify your email id to get the private key to cast your priceless vote. '+ otp +' is your OTP for email verfication.\nThank you.'
#     msg.set_content(content)
#     msg.add_alternative('''\
#         <!DOCTYPE html>
#         <html>
#             <body>
#                 Verify your email id to get the private key to cast your priceless vote.
#                 <h2 style="display:inline;">'''+ otp +'''</h2> is your OTP for email verfication.<br>
#                 Thank you.
#             </body>
#         </html>
#     ''', subtype='html')

#     try:
#         smtp = smtplib.SMTP_SSL('smtp.gmail.com', 465)
#         smtp.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
#         smtp.send_message(msg)
#         return [True, otp]
#     except Exception as e:
#         return [False, str(e)]

def send_email_otp(email_to):
    otp = ''.join(random.choice(string.digits) for _ in range(6))  # numeric OTP

    msg = EmailMessage()
    msg['From'] = EMAIL_ADDRESS
    msg['To'] = email_to
    msg['Subject'] = "OTP for Email Verification"
    msg.set_content(
        f"Verify your email to get the private key to cast your vote.\n\nYour OTP is: {otp}\n\nThank you."
    )

    msg.add_alternative(f"""
    <!DOCTYPE html>
    <html>
        <body>
            Verify your email to get the private key to cast your vote.<br>
            <h2 style="display:inline;">{otp}</h2> is your OTP for email verification.<br>
            Thank you.
        </body>
    </html>
    """, subtype='html')

    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
            smtp.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            smtp.send_message(msg)
        return True, otp
    except Exception as e:
        return False, str(e)

def send_email_private_key(email_to, private_key):
    msg = EmailMessage()
    msg['From'] = EMAIL_ADDRESS
    msg['To'] = email_to
    msg['Subject'] = 'PRIVATE KEY for vote casting (Do not share)'
    content = (
        "Paste the following private key exactly as it is to cast your vote.\n\n"
        f"{private_key}\n\n"
        "NOTE: DON'T REMOVE -----BEGIN PRIVATE KEY----- AND -----END PRIVATE KEY-----.\n\nThank you."
    )
    msg.set_content(content)

    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
            smtp.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            smtp.send_message(msg)
        return True, None         
    except Exception as e:
        return False, str(e)  
 

def generate_keys():

    key = ECC.generate(curve='P-256')
    private_key = key.export_key(format='PEM')
    public_key = key.public_key().export_key(format='PEM')

    return private_key, public_key

# def verify_vote(private_key, public_key, ballot):

#     try:
#         signer = DSS.new(ECC.import_key(private_key), 'fips-186-3')
#         verifier = DSS.new(ECC.import_key(public_key), 'fips-186-3')
        
#         ballot_hash = SHA3_256.new(ballot.encode())

#         ballot_signature = signer.sign(ballot_hash)

#         verifier.verify(ballot_hash, ballot_signature)
#         return [True, 'Your vote verfied and Ballot is signed successfully.', ballot_hash.hexdigest(), ballot_signature.hex()]
#     except Exception as e:
#         return [False, str(e), 'N/A', 'N/A']

def normalize_pem(key: str) -> str:
    """
    Fix PEM formatting issues: convert '\\n' to real newlines, 
    and ensure headers/footers exist.
    """
    if not key:
        raise ValueError("Empty key provided")
    key = key.strip().replace("\\n", "\n").replace("\r\n", "\n")
    if "-----BEGIN" not in key or "-----END" not in key:
        raise ValueError("Invalid PEM format")
    return key


#def verify_vote(private_key: str, public_key: str, ballot: str):
    """
    Verify a vote by signing ballot with private key and verifying using public key.
    Returns [success(bool), message(str), ballot_hash(str), signature(str)].
    """
    try:
        # Fix formatting if DB/email stored escaped keys
        priv = normalize_pem(private_key)
        pub = normalize_pem(public_key)

        # Load ECC keys
        priv_key_obj = ECC.import_key(priv)
        pub_key_obj = ECC.import_key(pub)

        # Create signer & verifier
        signer = DSS.new(priv_key_obj, 'fips-186-3')
        verifier = DSS.new(pub_key_obj, 'fips-186-3')

        # Hash the ballot
        ballot_hash = SHA3_256.new(ballot.encode())

        # Sign ballot using private key
        ballot_signature = signer.sign(ballot_hash)

        # Verify ballot using public key
        verifier.verify(ballot_hash, ballot_signature)

        return [
            True,
            "Your vote verified and Ballot is signed successfully.",
            ballot_hash.hexdigest(),
            ballot_signature.hex(),
        ]
    except Exception as e:
        return [False, f"Crypto error: {str(e)}", "N/A", "N/A"]
def verify_vote(private_key: str, public_key: str, ballot: str):
    try:
        priv = normalize_pem(private_key)
        pub = normalize_pem(public_key)

        priv_key_obj = ECC.import_key(priv)
        pub_key_obj = ECC.import_key(pub)

        signer = DSS.new(priv_key_obj, "fips-186-3")
        verifier = DSS.new(pub_key_obj, "fips-186-3")

        ballot_hash = SHA3_256.new(ballot.encode())
        ballot_signature = signer.sign(ballot_hash)

        verifier.verify(ballot_hash, ballot_signature)

        return [True, "Vote verified and signed successfully.",
                ballot_hash.hexdigest(), ballot_signature.hex()]

    except ValueError as e:
        return [False, f"Key error: {str(e)}", "N/A", "N/A"]
    except Exception as e:
        return [False, f"Crypto error: {str(e)}", "N/A", "N/A"]

def vote_count():
    parties_id = PoliticalParty.objects.values_list('party_id', flat = True)
    votes = Vote.objects.all()
    vote_result = {party: votes.filter(vote_party_id = party).count() for party in parties_id}
    # print(vote_result)
    return vote_result

# NEW FEATURE: Phone OTP Verification
def hash_otp(otp: str) -> str:
    """Hash OTP for secure storage"""
    return hashlib.sha256(otp.encode()).hexdigest()

def send_phone_otp(phone_number: str) -> tuple[bool, str]:
    """
    Send OTP to an Indian phone number via SMS using Fast2SMS.
    Returns (success: bool, otp: str) on success, (False, error_message: str) on failure.
    """
    # Generate 6-digit numeric OTP
    otp = ''.join(random.choice(string.digits) for _ in range(6))

    fast2sms_api_key = getattr(settings, 'FAST2SMS_API_KEY', None)
    use_mock_mode = getattr(settings, 'USE_MOCK_SMS', False)

    if not fast2sms_api_key:
        if use_mock_mode:
            # Mock mode: Log OTP to console for testing
            print(f"\n{'='*60}")
            print(f"MOCK SMS MODE - OTP for {phone_number}: {otp}")
            print(f"{'='*60}\n")
            return True, otp
        else:
            return False, "SMS service not configured. Please contact administrator."

    try:
        import requests

        # Fast2SMS's 'q' route expects a bare 10-digit Indian number, no country code.
        digits = ''.join(c for c in phone_number if c.isdigit())
        bare_number = digits[-10:]

        message_body = f"Your OTP for voting is: {otp}. Valid for 5 minutes. Do not share this OTP with anyone."

        response = requests.get(
            "https://www.fast2sms.com/dev/bulkV2",
            params={
                "authorization": fast2sms_api_key,
                "route": "q",
                "message": message_body,
                "numbers": bare_number,
            },
            timeout=10,
        )
        result = response.json()

        if result.get("return"):
            return True, otp
        else:
            return False, f"Failed to send SMS: {result.get('message')}"

    except Exception as e:
        print(f"Error sending SMS: {str(e)}")
        return False, f"Failed to send SMS: {str(e)}"


def send_phone_sms(phone_number: str, message_body: str) -> tuple[bool, str]:
    """
    Send a generic SMS using Twilio.
    Used for tamper alerts (not OTPs).
    Returns (success, result_or_error_message).
    """
    # Get Twilio credentials from settings
    twilio_account_sid = getattr(settings, "TWILIO_ACCOUNT_SID", None)
    twilio_auth_token = getattr(settings, "TWILIO_AUTH_TOKEN", None)
    twilio_phone_number = getattr(settings, "TWILIO_PHONE_NUMBER", None)

    # Check if Twilio is configured
    use_mock_mode = getattr(settings, "USE_MOCK_SMS", False)
    if not twilio_account_sid or not twilio_auth_token or not twilio_phone_number:
        if use_mock_mode:
            print(f"\n{'='*60}")
            print(f"MOCK SMS MODE - SMS to {phone_number}: {message_body}")
            print(f"{'='*60}\n")
            return True, "mock"
        return False, "SMS service not configured. Please contact administrator."

    # Check if Twilio library is available
    if not TWILIO_AVAILABLE:
        return False, "Twilio library not installed. Please install it using: pip install twilio"

    try:
        # Initialize Twilio client
        client = Client(twilio_account_sid, twilio_auth_token)

        # Normalize phone number (similar to OTP flow)
        phone_number = phone_number.replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
        if not phone_number.startswith("+"):
            if phone_number.startswith("0"):
                phone_number = phone_number[1:]
            DEFAULT_COUNTRY_CODE = "+91"
            if not phone_number.startswith("+"):
                phone_number = DEFAULT_COUNTRY_CODE + phone_number

        message = client.messages.create(
            body=message_body,
            from_=twilio_phone_number,
            to=phone_number,
        )

        if message.sid:
            return True, message.sid
        return False, "Failed to send SMS"
    except Exception as e:
        print(f"Error sending SMS: {str(e)}")
        return False, f"Failed to send SMS: {str(e)}"

