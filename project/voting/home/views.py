from django.shortcuts import render, redirect
from django.http import HttpResponse, JsonResponse
from django.template import loader
from django.views.decorators.csrf import ensure_csrf_cookie
from django.forms.models import model_to_dict
from django.contrib import messages
from django.conf import settings
from django.utils import timezone

from .models import Voters, PoliticalParty, Vote, VoteBackup, Block, MiningInfo
from .methods_module import normalize_pem, send_email_otp, generate_keys, verify_vote, send_email_private_key, vote_count, send_phone_otp, hash_otp, send_phone_sms

from Crypto.Hash import SHA3_256
from .merkle_tool import MerkleTools
import datetime, json, time, random, string
import os

try:
    import pandas as pd
except ImportError:
    pd = None

ts_data = {}

# Aadhaar Excel filename and candidate locations to try (safer than assuming parent dir)
_AADHAAR_FILENAME = "aadhaar_mock_data_100_records.xlsx"
_AADHAAR_CANDIDATES = [
    # original location (one level above BASE_DIR)
    os.path.abspath(os.path.join(settings.BASE_DIR, os.pardir, _AADHAAR_FILENAME)),
    # inside BASE_DIR (project/voting/)
    os.path.abspath(os.path.join(settings.BASE_DIR, _AADHAAR_FILENAME)),
    # inside the `home` app directory
    os.path.abspath(os.path.join(settings.BASE_DIR, "home", _AADHAAR_FILENAME)),
]

# Use the first candidate that exists, otherwise default to the original candidate
AADHAAR_EXCEL_PATH = next((p for p in _AADHAAR_CANDIDATES if os.path.exists(p)), _AADHAAR_CANDIDATES[0])


def _get_aadhaar_record(aadhaar_no):
    """
    Look up a single Aadhaar record from the Excel dataset.
    Returns (record_dict or None, error_message or None).
    """
    if pd is None:
        return None, "Server configuration error: pandas is not installed."

    if not os.path.exists(AADHAAR_EXCEL_PATH):
        return None, "Server configuration error: Aadhaar dataset file is missing."

    try:
        df = pd.read_excel(AADHAAR_EXCEL_PATH)
    except PermissionError:
        return None, (
            f"Permission denied reading Aadhaar dataset at {AADHAAR_EXCEL_PATH}. "
            "Ensure the file is readable by the Django process or move it into the project directory."
        )
    except Exception as exc:
        return None, f"Failed to read Aadhaar dataset. ({exc})"

    if df.empty:
        return None, "Aadhaar dataset is empty."

    first_col = df.columns[0]
    mask = df[first_col].astype(str).str.strip() == str(aadhaar_no).strip()
    rows = df[mask]
    if rows.empty:
        return None, None

    return rows.iloc[0].to_dict(), None


# Create your views here.

# -------------- Home (First time loading) --------------
@ensure_csrf_cookie
def home(request):
    return render(request, 'home.html')

# --------------- Authentication -------------------
def authentication(request):
    # Accept aadhar_no from POST (AJAX) or GET (fallback).
    aadhar_no = None
    if request.method == 'POST':
        aadhar_no = request.POST.get('aadhar_no')
    if not aadhar_no:
        aadhar_no = request.GET.get('aadhar_no')

    details = {'success': False}

    if not aadhar_no:
        details = {'error': 'Aadhar number not provided.'}
        return JsonResponse(details)
    
    # Validate Aadhar number: must be exactly 12 digits
    aadhar_no = aadhar_no.strip()
    if not aadhar_no.isdigit() or len(aadhar_no) != 12:
        details = {'error': 'Invalid Aadhar number. Please enter exactly 12 digits.'}
        return JsonResponse(details)

    # Look up Aadhaar in Excel dataset
    record, err = _get_aadhaar_record(aadhar_no)
    if err:
        # Dataset / server configuration issue
        details = {'error': err}
        return JsonResponse(details)

    if record is None:
        # Aadhaar not present in official dataset: do not allow voting
        details = {
            'error': 'Invalid Aadhar, Please Enter Correct Aadhar Number!'
        }
        return JsonResponse(details)

    # Map Excel columns to Voters fields (best-effort based on column names)
    lower_map = {str(k).lower(): k for k in record.keys()}

    def pick_column(*candidates):
        for cand in candidates:
            for key_lower, orig in lower_map.items():
                if cand in key_lower:
                    return orig
        return None

    name_col = pick_column("name")
    dob_col = pick_column("dob", "date")
    pincode_col = pick_column("pincode", "pin", "zip")
    region_col = pick_column("region", "city", "state", "address")
    email_col = pick_column("email", "mail")
    phone_col = pick_column("phone", "mobile", "contact")
    photo_col = pick_column("photo_url", "photo", "image_url", "image", "pic")

    voter_defaults = {}
    if name_col:
        voter_defaults["name"] = str(record.get(name_col) or "").strip()
    if dob_col and record.get(dob_col):
        dob_val = record.get(dob_col)
        try:
            if isinstance(dob_val, datetime.date):
                voter_defaults["dob"] = dob_val
            else:
                voter_defaults["dob"] = datetime.datetime.strptime(
                    str(dob_val).split(" ")[0], "%Y-%m-%d"
                ).date()
        except Exception:
            pass
    if pincode_col:
        voter_defaults["pincode"] = str(record.get(pincode_col) or "").strip()
    if region_col:
        voter_defaults["region"] = str(record.get(region_col) or "").strip()
    if email_col:
        voter_defaults["email"] = str(record.get(email_col) or "").strip()
    if phone_col:
        voter_defaults["phone_number"] = str(record.get(phone_col) or "").strip()
    if photo_col:
        raw_photo = record.get(photo_col)
        photo_str = str(raw_photo).strip() if raw_photo is not None else ""
        # pandas uses NaN for missing cells; avoid rendering src="nan"
        if photo_str.lower() != "nan":
            voter_defaults["profile_pic"] = photo_str

    try:
        # Only allow voters that exist in the Excel dataset.
        voter, created = Voters.objects.get_or_create(
            uuid=aadhar_no,
            defaults=voter_defaults or {
                "name": aadhar_no,
                "dob": datetime.date(2000, 1, 1),
                "pincode": "000000",
                "region": "N/A",
            },
        )

        # Keep DB record in sync with dataset (without altering vote state)
        for field, value in voter_defaults.items():
            setattr(voter, field, value)
        voter.save()

        request.session['uuid'] = aadhar_no
        render_html = loader.render_to_string('candidate_details.html', {'details': voter})
        if voter.vote_done:
            details = {
                'error': 'You have already casted your vote.'
            }
        else:
            details = {
                'success': True,
                'html': render_html,
                'details': model_to_dict(voter)
            }
    except Exception:
        details = {'error': 'An internal error occurred while authenticating.'}

    return JsonResponse(details)


# --------- Send otp for email verfication -----------
# def send_otp(request):
#     email_input = request.GET.get('email-id')

#     # [success, result] = send_email_otp(email_input)
#     [success, result] = [True, '0']

#     json = {'success': success}
#     if success:
#         request.session['otp'] = result
#         request.session['email-id'] = email_input
#         request.session['email-verified'] = False
#     else:
#         json['error'] = result

#     return JsonResponse(json)

def send_otp(request):
    # Email is taken from Aadhaar dataset (synced to DB) to avoid user tampering.

    # Enforce phone verification before email OTP
    voter_uuid = request.session.get('uuid')
    if not voter_uuid:
        return JsonResponse({'success': False, 'error': 'Session expired. Please authenticate again.'})
    try:
        voter = Voters.objects.get(uuid=voter_uuid)
        if not voter.is_phone_verified:
            return JsonResponse({'success': False, 'error': 'Phone verification required before email verification.'})
    except Voters.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Voter not found. Please authenticate again.'})

    email_input = (voter.email or '').strip()
    if not email_input:
        return JsonResponse({'success': False, 'error': 'No email found for this Aadhaar in the dataset.'})

    success, result = send_email_otp(email_input)

    response = {'success': success}
    if success:
        request.session['otp'] = result
        request.session['email-id'] = email_input
        request.session['email-verified'] = False
    else:
        response['error'] = result  # show SMTP error message

    return JsonResponse(response)

# -------- Verify email with provided otp ----------
# def verify_otp(request):

    otp_input = request.GET.get('otp-input')
    json = {'success': False}
    if otp_input == request.session['otp']:
        voter = Voters.objects.get(uuid = request.session['uuid'])
        voter.email = request.session['email-id']
        voter.save()
        json['success'] = True
        request.session['email-verified'] = True

    return JsonResponse(json)


#def verify_otp(request):
    otp_input = request.POST.get('otp-input') or request.GET.get('otp-input')
    json = {'success': False}

    session_otp = request.session.get('otp')
    voter_uuid = request.session.get('uuid')
    email_id = request.session.get('email-id')

    if not otp_input or not session_otp:
        json['error'] = 'OTP not provided or session expired'
        return JsonResponse(json)

    if otp_input.strip() != str(session_otp).strip():
        json['error'] = 'Invalid OTP'
        return JsonResponse(json)

    # OTP matches
    try:
        voter = Voters.objects.get(uuid=voter_uuid)
        voter.email = email_id

        # generate ECC keys
        private_key, public_key = generate_keys()
        voter.public_key = public_key  # make sure Voters model has this field
        voter.save()

        # send private key via email
        sent, error = send_email_private_key(email_id, private_key)
        if not sent:
            json['error'] = f'OTP verified but failed to send private key: {error}'
            return JsonResponse(json)

        # success
        request.session['email-verified'] = True
        request.session['public_key'] = public_key
        json['success'] = True
        json['message'] = 'OTP verified. Private key sent to your email.'

    except Voters.DoesNotExist:
        json['error'] = 'Voter not found for this session UUID'

    return JsonResponse(json)
#def verify_otp(request):
    otp_input = request.POST.get("otp-input")
    json = {"success": False}

    if otp_input == request.session.get("otp"):
        voter = Voters.objects.get(uuid=request.session["uuid"])
        email_id = request.session["email-id"]

        # Save email
        voter.email = email_id
        voter.save()

        # Generate key pair ONCE
        private_key, public_key = generate_keys()

        # Store public key for later verification
        request.session["public-key"] = public_key
        request.session["email-verified"] = True

        # Send private key to user’s email
        sent, error = send_email_private_key(email_id, private_key)
        if not sent:
            json["error"] = f"Could not send private key: {error}"
            return JsonResponse(json)

        json["success"] = True
        json["message"] = "OTP verified. Private key has been sent to your email."

    return JsonResponse(json)
def verify_otp(request):
    otp_input = request.POST.get("otp-input") or request.GET.get("otp-input")
    json = {"success": False}

    # Get session data safely
    session_otp = str(request.session.get("otp", "")).strip()
    voter_uuid = request.session.get("uuid")
    email_id = request.session.get("email-id")

    if not otp_input:
        json["error"] = "No OTP provided"
        return JsonResponse(json)

    if not session_otp:
        json["error"] = "OTP session expired, please request again"
        return JsonResponse(json)

    # Compare input vs session OTP
    if str(otp_input).strip() != session_otp:
        json["error"] = "Invalid OTP"
        return JsonResponse(json)

    # OTP matches
    try:
        voter = Voters.objects.get(uuid=voter_uuid)
        voter.email = email_id

        # Generate ECC keys
        private_key, public_key = generate_keys()
        voter.public_key = public_key
        voter.save()

        # Send private key via email
        sent, error = send_email_private_key(email_id, private_key)
        if not sent:
            json["error"] = f"OTP verified but private key email failed: {error}"
            return JsonResponse(json)

        # Mark verified
        request.session["email-verified"] = True
        request.session["public-key"] = public_key

        json["success"] = True
        json["message"] = "OTP verified successfully. Private key sent to your email."
        # NEW FEATURE: Phone OTP Verification - Mark that phone verification is needed
        json["phone_verification_required"] = True

    except Voters.DoesNotExist:
        json["error"] = "Voter not found for this session UUID"

    return JsonResponse(json)

# NEW FEATURE: Phone OTP Verification
# --------- Send OTP for phone verification -----------
def send_phone_otp_endpoint(request):
    """Send OTP to user's registered phone number from Aadhaar dataset."""
    json = {"success": False}

    voter_uuid = request.session.get('uuid')
    if not voter_uuid:
        json["error"] = "Session expired. Please authenticate again."
        return JsonResponse(json)

    try:
        voter = Voters.objects.get(uuid=voter_uuid)

        # Use phone number that came from the Aadhaar dataset
        phone_input = (voter.phone_number or "").strip()
        if not phone_input:
            json["error"] = "No phone number found for this Aadhaar in the dataset."
            return JsonResponse(json)

        # Basic validation & normalisation
        cleaned_phone = (
            phone_input.replace(" ", "")
            .replace("-", "")
            .replace("(", "")
            .replace(")", "")
        )
        # Allow leading '+'
        if cleaned_phone.startswith("+"):
            cleaned_phone = cleaned_phone[1:]

        if not cleaned_phone.isdigit() or len(cleaned_phone) < 10 or len(cleaned_phone) > 15:
            json["error"] = "Invalid phone number in dataset. Please contact administrator."
            return JsonResponse(json)

        # 10-digit numbers are bare local numbers (India); prepend the country code.
        # Anything longer is assumed to already include a country code.
        if len(cleaned_phone) == 10:
            cleaned_phone = "91" + cleaned_phone
        phone_input = "+" + cleaned_phone  # normalised E.164-style

        # Generate and send OTP
        success, result = send_phone_otp(phone_input)
        
        if success:
            # Store phone number and hashed OTP with expiry (5 minutes)
            voter.phone_number = phone_input
            voter.phone_otp = hash_otp(result)  # Store hashed OTP
            voter.phone_otp_expiry = timezone.now() + datetime.timedelta(minutes=5)
            voter.is_phone_verified = False  # Reset verification status
            voter.save()
            
            # Store OTP in session for verification (temporary, for comparison)
            request.session['phone_otp'] = result
            request.session['phone-number'] = phone_input
            
            json["success"] = True
            json["message"] = f"OTP sent to {phone_input}"
        else:
            json["error"] = f"Failed to send OTP: {result}"

    except Voters.DoesNotExist:
        json["error"] = "Voter not found"
    except Exception as e:
        json["error"] = f"Error: {str(e)}"

    return JsonResponse(json)

# --------- Verify phone OTP -----------
def verify_phone_otp(request):
    """Verify phone OTP entered by user"""
    otp_input = request.POST.get("phone-otp-input") or request.GET.get("phone-otp-input")
    json = {"success": False}

    if not otp_input:
        json["error"] = "OTP not provided"
        return JsonResponse(json)

    voter_uuid = request.session.get('uuid')
    if not voter_uuid:
        json["error"] = "Session expired"
        return JsonResponse(json)

    try:
        voter = Voters.objects.get(uuid=voter_uuid)
        
        # Check if OTP exists and hasn't expired
        if not voter.phone_otp or not voter.phone_otp_expiry:
            json["error"] = "No OTP found. Please request a new OTP."
            return JsonResponse(json)

        if timezone.now() > voter.phone_otp_expiry:
            json["error"] = "OTP expired. Please request a new OTP."
            voter.phone_otp = None
            voter.phone_otp_expiry = None
            voter.save()
            return JsonResponse(json)

        # Verify OTP by comparing hashes
        input_otp_hash = hash_otp(str(otp_input).strip())
        
        if input_otp_hash == voter.phone_otp:
            # OTP verified successfully
            voter.is_phone_verified = True
            voter.phone_otp = None  # Invalidate OTP after use
            voter.phone_otp_expiry = None
            voter.save()
            
            request.session['phone-verified'] = True
            
            json["success"] = True
            json["message"] = "Phone number verified successfully"
            json["next_step"] = "email_verification"
        else:
            json["error"] = "Invalid OTP"

    except Voters.DoesNotExist:
        json["error"] = "Voter not found"
    except Exception as e:
        json["error"] = f"Error: {str(e)}"

    return JsonResponse(json)

# --------- On successful email verfication show all parties options ----------
#def get_parties(request):
    
    party_list = {}
    if request.session['email-verified']:

        private_key, public_key = generate_keys()

        # send_email_private_key(request.session['email-id'], private_key)
        print(private_key)

        request.session['public-key'] = public_key

        parties = list(PoliticalParty.objects.all())
        parties = [model_to_dict(party) for party in parties]

        render_html = loader.render_to_string('voting.html', {'parties': parties})

        party_list = {
            'html': render_html,
            'parties': parties
        }

    return JsonResponse(party_list)

# ------------- Save vote in database ------------------------
#def create_vote(request):

    uuid = request.session['uuid']

    private_key = request.GET.get('private-key')
    public_key = request.session['public-key']

    selected_party_id = request.GET.get('selected-party-id')

    curr = timezone.now()

    ballot = f'{uuid}|{selected_party_id}|{curr.timestamp()}'
    
    status = verify_vote(private_key, public_key, ballot)
    context = {'success': status[0], 'status': status[1]}

    if status[0]:
        try:
            Vote(uuid = uuid, vote_party_id = selected_party_id, timestamp = curr).save()
            VoteBackup(uuid = uuid, vote_party_id = selected_party_id, timestamp = curr).save()
            voter = Voters.objects.get(uuid = request.session['uuid'])
            voter.vote_done = True
            voter.save()
        except Exception as e:
            context['status'] = 'We are not able to save your vote. Please try again. '+str(e)+'.'
            
    html = loader.render_to_string('final-status.html', {
        'ballot': status[2], 'ballot_signature': status[3], 'status': status[1]})
    context['html'] = html

    return JsonResponse(context)
#def create_vote(request):
    uuid = request.session['uuid']

    if request.method == "POST":
        private_key = request.POST.get('private-key')
        selected_party_id = request.POST.get('selected-party-id')
    else:
        return JsonResponse({'success': False, 'status': 'Invalid request method'})

    public_key = request.session.get('public-key')
    curr = timezone.now()

    if not private_key or not public_key:
        return JsonResponse({'success': False, 'status': 'Missing keys'})

    ballot = f'{uuid}|{selected_party_id}|{curr.timestamp()}'
    
    status = verify_vote(private_key, public_key, ballot)
    context = {'success': status[0], 'status': status[1]}

    if status[0]:
        try:
            Vote(uuid=uuid, vote_party_id=selected_party_id, timestamp=curr).save()
            VoteBackup(uuid=uuid, vote_party_id=selected_party_id, timestamp=curr).save()
            voter = Voters.objects.get(uuid=uuid)
            voter.vote_done = True
            voter.save()
        except Exception as e:
            context['status'] = f"We are not able to save your vote. Please try again. {str(e)}."

    html = loader.render_to_string('final-status.html', {
        'ballot': status[2], 'ballot_signature': status[3], 'status': status[1]})
    context['html'] = html

    return JsonResponse(context)
def get_parties(request):
    party_list = {}
    voter_uuid = request.session.get('uuid')
    if not voter_uuid:
        return JsonResponse({'error': 'Session expired. Please authenticate again.'})

    # Check if phone is verified
    try:
        voter = Voters.objects.get(uuid=voter_uuid)
        if not voter.is_phone_verified:
            return JsonResponse({
                'error': 'Phone number verification required before voting.',
                'phone_verification_required': True
            })
    except Voters.DoesNotExist:
        return JsonResponse({'error': 'Voter not found'})

    # Require email verification before loading parties
    if not request.session.get('email-verified'):
        return JsonResponse({
            'error': 'Email verification required before voting.',
            'email_verification_required': True
        })

    parties = list(PoliticalParty.objects.all())
    parties = [model_to_dict(party) for party in parties]

    render_html = loader.render_to_string('voting.html', {'parties': parties})

    party_list = {
        'html': render_html,
        'parties': parties
    }

    return JsonResponse(party_list)

def create_vote(request):
    uuid = request.session.get("uuid")
    public_key = request.session.get("public-key")

    if request.method != "POST":
        return JsonResponse({"success": False, "status": "Invalid request method"})

    # NEW FEATURE: Phone OTP Verification - Check phone verification before allowing vote
    try:
        voter = Voters.objects.get(uuid=uuid)
        if not voter.is_phone_verified:
            return JsonResponse({"success": False, "status": "Phone number verification required before voting."})
    except Voters.DoesNotExist:
        return JsonResponse({"success": False, "status": "Voter not found"})

    private_key = request.POST.get("private-key")
    selected_party_id = request.POST.get("selected-party-id")

    if not private_key or not public_key:
        return JsonResponse({"success": False, "status": "Missing keys"})

    try:
        private_key = normalize_pem(private_key)
        public_key = normalize_pem(public_key)

        curr = timezone.now()
        ballot = f"{uuid}|{selected_party_id}|{curr.timestamp()}"

        status = verify_vote(private_key, public_key, ballot)
        context = {"success": status[0], "status": status[1]}

        if status[0]:
            # Save the vote
            try:
                Vote(uuid=uuid, vote_party_id=selected_party_id, timestamp=curr).save()
                VoteBackup(uuid=uuid, vote_party_id=selected_party_id, timestamp=curr).save()
                voter = Voters.objects.get(uuid=uuid)
                voter.vote_done = True
                voter.save()
            except Exception as e:
                context["status"] = f"We could not save your vote. {str(e)}"

        html = loader.render_to_string(
            "final-status.html",
            {
                "ballot": status[2],
                "ballot_signature": status[3],
                "status": status[1],
            },
        )
        context["html"] = html
        return JsonResponse(context)

    except Exception as e:
        return JsonResponse({"success": False, "status": f"Vote failed: {str(e)}"})

# -------------- create Dummy Data ------------------
def create_dummy_data(request):
    to_do = {
        'createRandomVoters': json.loads(request.GET.get('createRandomVoters')) if request.GET.get('createRandomVoters') else None,
        'createPoliticianParties': json.loads(request.GET.get('createPoliticianParties')) if request.GET.get('createPoliticianParties') else None,
        'castRandomVote': json.loads(request.GET.get('castRandomVote')) if request.GET.get('castRandomVote') else None,
    }
    if to_do['createRandomVoters'] or to_do['createPoliticianParties'] or to_do['castRandomVote']:
        dummy_data_input(to_do)
        return JsonResponse({'success': True})
    return render(request, 'create-dummy-data.html')
    # dummy_data_input()
    # return redirect('/')

# -------------- Show Vote count so far -----------
def show_result(request):
    vote_result = vote_count()
    vote_result = dict(reversed(sorted(vote_result.items(), key = lambda vr:(vr[1], vr[0]))))
    results = []
    political_parties = PoliticalParty.objects.all()
    i=0
    for party_id, votecount in vote_result.items():
        i+=1
        party = political_parties.get(party_id = party_id)
        results.append({
            'sr': i,
            'party_name': party.party_name,
            'party_symbol': party.party_logo,
            'vote_count': votecount
        })
    return render(request, 'show-result.html', {'results': results})

# ------------- Show Block Mining Page -------------
def mine_block(request):
    to_seal_votes_count = Vote.objects.all().filter(block_id=None).count()
    return render(request, 'mine-block.html', {'data': to_seal_votes_count})

# ----------------- Start mining on button click ---------------
def start_mining(request):
    data = create_block()
    html = loader.render_to_string('mined-blocks.html', data)
    return JsonResponse({'html': html})

# Create block [called in start_mining()]
def create_block():

    # Get or initialize mining info up to last mining.
    # This is made robust so that even if you delete all blocks from the
    # admin panel, the next mined block will automatically start from
    # a clean "genesis" state without needing a separate reset URL.
    mining_info = MiningInfo.objects.all().first()
    if mining_info is None:
        # Fresh start: no mining info yet
        mining_info = MiningInfo.objects.create(
            prev_hash="0" * 64,
            last_block_id="0",
        )

    # If all blocks were deleted manually, force a fresh genesis-like start.
    if Block.objects.count() == 0:
        prev_hash = "0" * 64
        curr_block_id = last_block_id = 0
    else:
        prev_hash = mining_info.prev_hash or ("0" * 64)
        try:
            curr_block_id = last_block_id = int(mining_info.last_block_id or "0")
        except ValueError:
            curr_block_id = last_block_id = 0
    
    non_sealed_votes = Vote.objects.all().filter(block_id=None).order_by('timestamp')
    non_sealed_votes_BACKUP = VoteBackup.objects.all().filter(block_id=None).order_by('timestamp')

    # Get settings for per block mining
    txn_per_block = settings.TRANSACTIONS_PER_BLOCK
    number_of_blocks = int( non_sealed_votes.count()/txn_per_block )

    # Puzzle requirement: '0' * n (n leading zeros)
    puzzle, pcount = settings.PUZZLE, settings.PLENGTH
    
    time_start = time.time()

    result = []

    ts_data['progress'] = True
    ts_data['status'] = 'Mining has been Initialised.'
    ts_data['completed'] = 0

    for _ in range(number_of_blocks):
        # As soon as block_id set to the transaction it is automatically removed from 'non_sealed_vote'
        # Hence always top 'txn_per_block' transactions belong to one block
        block_transactions = non_sealed_votes[:txn_per_block]
        block_transactions_BACKUP = non_sealed_votes_BACKUP[:txn_per_block]
        
        root = MerkleTools()
        root.add_leaf([f'{tx.uuid}|{tx.vote_party_id}|{tx.timestamp}' for tx in block_transactions], True)
        root.make_tree()
        merkle_h = root.get_merkle_root()
        # Try to seal the block and generate valid hash
        nonce = 0
        timestamp = timezone.now()
        while True:
            enc = f'{prev_hash}{merkle_h}{nonce}{timestamp.timestamp()}'.encode('utf-8')
            h = SHA3_256.new(enc).hexdigest()
            if h[:pcount] == puzzle:
                break
            nonce += 1

        # Create the block
        curr_block_id += 1
        Block(id=curr_block_id, prev_hash=prev_hash, merkle_hash=merkle_h, this_hash=h, nonce=nonce, timestamp=timestamp).save()

        result.append({
            'block_id': curr_block_id, 'prev_hash': prev_hash, 'merkle_hash': merkle_h, 'this_hash': h, 'nonce': nonce
        })
        
        # Set this hash as prev hash
        prev_hash = h
        
        # Set block_id to every transaction
        for txn in block_transactions:
            txn.block_id = str(curr_block_id)
            txn.save()
        for txn in block_transactions_BACKUP:
            txn.block_id = str(curr_block_id)
            txn.save()

        ts_data['status'] = str(curr_block_id - last_block_id) + ' blocks have been mined. (' + str((curr_block_id - last_block_id)*txn_per_block) + ' vote transactions have been sealed.)'
        ts_data['completed'] = round((curr_block_id - last_block_id)*100/number_of_blocks)
    time_end = time.time()

    time_taken = time_end - time_start
    if time_taken < 0.0000:
        time_taken = 0.000000

    # Save current Mining info
    mining_info.prev_hash = prev_hash
    mining_info.last_block_id = str(curr_block_id)
    mining_info.id = 0
    mining_info.save()

    data = {
        'time_taken': round(time_end-time_start, 6),
        'result': result
    }

    ts_data['progress'] = False

    return data

def dummy_data_input(to_do):

    ts_data['progress'] = True
    ts_data['status'] = 'Deleting current Data.'
    ts_data['completed'] = 0
    
    PoliticalParty.objects.all().delete()
    Voters.objects.all().delete()
    Vote.objects.all().delete()
    Block.objects.all().delete()
    VoteBackup.objects.all().delete()
    MiningInfo.objects.all().delete()

    ts_data['completed'] = 100
    ts_data['status'] = 'Deleted current Data.'

    MiningInfo(id = 0, prev_hash = '0'*64, last_block_id = '0').save()

    if to_do['createPoliticianParties']:

        parties = {
            'bjp': {
                'party_id': 'bjp',
                'party_name': 'Bhartiya Janta Party (BJP)',
                'party_logo': 'https://upload.wikimedia.org/wikipedia/en/thumb/1/1e/Bharatiya_Janata_Party_logo.svg/180px-Bharatiya_Janata_Party_logo.svg.png',
                'candidate_name': '',
                'candidate_profile_pic': ''
                },
            'congress': {
                'party_id': 'congress',
                'party_name': 'Indian National Congress',
                'party_logo': 'https://upload.wikimedia.org/wikipedia/commons/thumb/4/45/Flag_of_the_Indian_National_Congress.svg/250px-Flag_of_the_Indian_National_Congress.svg.png',
                'candidate_name': '',
                'candidate_profile_pic': ''
                },
            'bsp': {
                'party_id': 'bsp',
                'party_name': 'Bahujan Samaj Party',
                'party_logo': 'https://upload.wikimedia.org/wikipedia/commons/thumb/d/d2/Elephant_Bahujan_Samaj_Party.svg/1200px-Elephant_Bahujan_Samaj_Party.svg.png',
                'candidate_name': '',
                'candidate_profile_pic': ''
            },
            'cpi': {
                'party_id': 'cpi',
                'party_name': 'Communist Party of India',
                'party_logo': 'https://upload.wikimedia.org/wikipedia/commons/thumb/1/18/CPI-banner.svg/200px-CPI-banner.svg.png',
                'candidate_name': '',
                'candidate_profile_pic': ''
            },
            'nota': {
                'party_id': 'nota',
                'party_name': 'None of the above (NOTA)',
                'party_logo': 'https://upload.wikimedia.org/wikipedia/commons/thumb/a/a4/NOTA_Option_Logo.png/220px-NOTA_Option_Logo.png',
                'candidate_name': '',
                'candidate_profile_pic': ''
            }
        }

        ts_data['completed'] = 0
        ts_data['status'] = 'Creating parties.'

        # Create Parties
        for party in parties.values():
            PoliticalParty(party_id = party['party_id'], party_name = party['party_name'], party_logo = party['party_logo']).save()
            curr = list(parties.keys()).index(party['party_id'])+1
            ts_data['completed'] = round(curr*100/len(parties))

    if to_do['createRandomVoters']:

        ts_data['completed'] = 0
        ts_data['status'] = 'Creating voters.'

        # Create Voters
        no_of_voters = 10
        for i in range(1, no_of_voters+1):
            # uuid = ''.join(random.choice(string.digits) for _ in range(12))
            uuid = i
            name = ''.join(random.choice(string.ascii_lowercase + string.ascii_uppercase) for _ in range(12))
            dob = datetime.date(random.randint(1980, 2002), random.randint(1, 12), random.randint(1, 28))
            pincode = ''.join(random.choice(string.digits) for _ in range(6))
            region = ''.join(random.choice(string.ascii_lowercase + string.ascii_uppercase) for _ in range(20))
            voter = Voters(uuid = uuid, name = name, dob = dob, pincode = pincode, region = region).save()
            ts_data['completed'] = round(i*100/no_of_voters)

    if to_do['castRandomVote'] and to_do['createRandomVoters'] and to_do['createPoliticianParties']:

        ts_data['completed'] = 0
        ts_data['status'] = 'Creating votes.'

        # Create Votes
        party_ids = list(parties.keys())
        for i in range(1, no_of_voters+1):
            curr_time = timezone.now()
            party_id = party_ids[random.randint(0,len(party_ids)-1)]
            Vote(uuid = i, vote_party_id = party_id, timestamp = curr_time).save()
            VoteBackup(uuid = i, vote_party_id = party_id, timestamp = curr_time).save()
            voter = Voters.objects.get(uuid=i)
            voter.vote_done = True
            voter.save()
            ts_data['completed'] = round(i*100/no_of_voters)

    ts_data['status'] = 'Finishing task.'
    ts_data['progress'] = False

def blockchain(request):
    blocks = Block.objects.all()
    return render(request, 'blockchain.html', {'blocks':blocks})

def block_info(request):
    try:
        block = Block.objects.get(id=request.GET.get('id'))
        confirmed_by = (Block.objects.all().count() - block.id) + 1

        votes = Vote.objects.filter(block_id=request.GET.get('id'))
        vote_hashes = [SHA3_256.new((f'{vote.uuid}|{vote.vote_party_id}|{vote.timestamp}').encode('utf-8')).hexdigest() for vote in votes]

        root = MerkleTools()
        root.add_leaf([f'{vote.uuid}|{vote.vote_party_id}|{vote.timestamp}' for vote in votes], True)
        root.make_tree()
        merkle_hash = root.get_merkle_root()
        tampered = block.merkle_hash != merkle_hash

        # If tampering is detected, notify affected voters (once per vote).
        if tampered:
            for vote in votes:
                if getattr(vote, "tamper_alert_sent", False):
                    continue
                try:
                    voter = Voters.objects.get(uuid=vote.uuid)
                except Voters.DoesNotExist:
                    continue

                phone = (voter.phone_number or "").strip()
                if not phone:
                    continue

                message_body = (
                    f"ALERT: A tampered vote was detected in Block #{block.id}. "
                    f"Please contact election administration for assistance."
                )
                ok, _ = send_phone_sms(phone, message_body)
                if ok:
                    vote.tamper_alert_sent = True
                    vote.tamper_alert_sent_at = timezone.now()
                    vote.save(update_fields=["tamper_alert_sent", "tamper_alert_sent_at"])
        
        context = {
            'this_block': block,
            'confirmed_by': confirmed_by,
            'votes': zip(votes, vote_hashes),
            're_merkle_hash': merkle_hash,
            'isTampered': tampered,
        }
        return render(request, 'block-info.html', context)
    except Exception as e:
        print(str(e))
        return render(request, 'block-info.html')

def sync_block(request):
    try:
        block_id = request.GET.get('block-id')
        print(block_id)
        print(Vote.objects.filter(block_id=block_id))
        backup_votes = VoteBackup.objects.filter(block_id=block_id).order_by('timestamp')
        print(backup_votes)
        for vote in backup_votes:
            x_vote = Vote.objects.get(uuid=vote.uuid)
            x_vote.vote_party_id = vote.vote_party_id
            x_vote.timestamp = vote.timestamp
            x_vote.block_id = vote.block_id
            x_vote.save()
        return JsonResponse({'success': True})
    except Exception as e:
        print(e)
        return JsonResponse({'success': False})

def verify_block(request):
    selected = request.GET.getlist('selected[]')
    context = {}
    for s_block in selected:
        block = Block.objects.get(id=s_block)
        votes = Vote.objects.filter(block_id=s_block)
        vote_hashes = [SHA3_256.new((f'{vote.uuid}|{vote.vote_party_id}|{vote.timestamp}').encode('utf-8')).hexdigest() for vote in votes]

        root = MerkleTools()
        root.add_leaf([f'{vote.uuid}|{vote.vote_party_id}|{vote.timestamp}' for vote in votes], True)
        root.make_tree()
        merkle_hash = root.get_merkle_root()
        tampered = block.merkle_hash != merkle_hash

        # If tampering is detected, notify affected voters (once per vote).
        if tampered:
            for vote in votes:
                if getattr(vote, "tamper_alert_sent", False):
                    continue
                try:
                    voter = Voters.objects.get(uuid=vote.uuid)
                except Voters.DoesNotExist:
                    continue

                phone = (voter.phone_number or "").strip()
                if not phone:
                    continue

                message_body = (
                    f"ALERT: A tampered vote was detected in Block #{block.id}. "
                    f"Please contact election administration for assistance."
                )
                ok, _ = send_phone_sms(phone, message_body)
                if ok:
                    vote.tamper_alert_sent = True
                    vote.tamper_alert_sent_at = timezone.now()
                    vote.save(update_fields=["tamper_alert_sent", "tamper_alert_sent_at"])

        context[s_block] = tampered

    return JsonResponse(context)

def track_server(request):
    return JsonResponse(ts_data)


def aadhaar_from_excel(request):
    """
    Simple API that exposes the Aadhaar mock Excel as JSON.

    - GET /api/aadhaar/              -> returns all rows
    - GET /api/aadhaar/?aadhaar=XXX  -> filters by first column matching XXX
    """
    if pd is None:
        return JsonResponse(
            {"error": "pandas is not installed on the server"},
            status=500,
        )

    if not os.path.exists(AADHAAR_EXCEL_PATH):
        return JsonResponse(
            {"error": "Excel file not found on server"},
            status=500,
        )

    try:
        # Read the first sheet from the Excel file
        df = pd.read_excel(AADHAAR_EXCEL_PATH)
    except Exception as exc:
        return JsonResponse(
            {"error": "Failed to read Excel file", "details": str(exc)},
            status=500,
        )

    aadhaar_no = request.GET.get("aadhaar") or request.GET.get("aadhaar_no")

    if aadhaar_no:
        # Filter by first column, treating values as strings
        first_col = df.columns[0]
        mask = df[first_col].astype(str) == str(aadhaar_no).strip()
        df = df[mask]

    data = df.to_dict(orient="records")
    return JsonResponse(data, safe=False)


def reset_blockchain(request):
    """
    Testing helper: reset blockchain metadata so the next mined block
    starts at ID 1 with a zero prev_hash-like genesis block.
    Does NOT touch voters or the voting workflow.
    """
    # Clear all existing blocks
    Block.objects.all().delete()

    # Detach existing votes from old blocks so they can be re-mined
    Vote.objects.update(block_id=None)
    VoteBackup.objects.update(block_id=None)

    # Reset or create MiningInfo so that create_block() starts from scratch
    mining_info = MiningInfo.objects.all().first()
    if mining_info is None:
        mining_info = MiningInfo()

    mining_info.prev_hash = "0" * 64
    mining_info.last_block_id = "0"
    mining_info.save()

    return JsonResponse(
        {
            "success": True,
            "status": "Blockchain has been reset. The next mined block will start from ID 1 with zero prev_hash.",
        }
    )


def reset_current_voter_vote(request):
    """
    Testing helper: clear the current session voter's vote so you can vote again.

    - Uses the Aadhaar stored in session['uuid'].
    - Deletes Vote and VoteBackup for that uuid.
    - Resets vote_done and phone/email verification flags.
    """
    uuid = request.session.get("uuid")
    if not uuid:
        return JsonResponse(
            {"success": False, "status": "No voter in session. Authenticate with Aadhaar first."}
        )

    try:
        voter = Voters.objects.get(uuid=uuid)
    except Voters.DoesNotExist:
        return JsonResponse({"success": False, "status": "Voter not found."})

    # Delete any existing votes for this Aadhaar
    Vote.objects.filter(uuid=uuid).delete()
    VoteBackup.objects.filter(uuid=uuid).delete()

    # Reset voter flags so the flow can run again
    voter.vote_done = False
    voter.is_phone_verified = False
    voter.phone_otp = None
    voter.phone_otp_expiry = None
    # Keep email and public key if you want, or clear them for full flow:
    # voter.public_key = None
    voter.save()

    # Clear session flags related to verification/keys
    for key in ["phone-verified", "email-verified", "public-key", "otp", "email-id"]:
        if key in request.session:
            del request.session[key]

    return JsonResponse(
        {"success": True, "status": f"Vote for Aadhaar {uuid} has been reset. You can vote again."}
    )


def reset_vote_page(request):
    """
    Simple HTML form endpoint to reset a vote by Aadhaar number.
    This is mainly for testing/demo, not for real elections.
    """
    status = None

    if request.method == "POST":
        aadhaar_no = (request.POST.get("aadhaar_no") or "").strip()
        if not aadhaar_no:
            status = "Please enter an Aadhaar number."
        else:
            # Delete votes and reset flags for that Aadhaar
            Vote.objects.filter(uuid=aadhaar_no).delete()
            VoteBackup.objects.filter(uuid=aadhaar_no).delete()
            try:
                voter = Voters.objects.get(uuid=aadhaar_no)
                voter.vote_done = False
                voter.is_phone_verified = False
                voter.phone_otp = None
                voter.phone_otp_expiry = None
                voter.save()
                status = f"Vote for Aadhaar {aadhaar_no} has been reset."
            except Voters.DoesNotExist:
                status = f"No voter found for Aadhaar {aadhaar_no}."

    return render(request, "reset_vote.html", {"status": status})
