from django.contrib import admin
from django.urls import path

from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('authentication/', views.authentication, name='authentication'),
    path('get-parties/', views.get_parties, name='get-parties'),
    path('create-vote/', views.create_vote, name='create-vote'),
    path('reset-blockchain/', views.reset_blockchain, name='reset-blockchain'),
    path('reset-vote/', views.reset_vote_page, name='reset-vote'),
    path('reset-current-vote/', views.reset_current_voter_vote, name='reset-current-vote'),
    path('send-otp/', views.send_otp, name='send-otp'),
    path('verify-otp/', views.verify_otp, name='verify-otp'),
    # NEW FEATURE: Phone OTP Verification
    path('send-phone-otp/', views.send_phone_otp_endpoint, name='send-phone-otp'),
    path('verify-phone-otp/', views.verify_phone_otp, name='verify-phone-otp'),
    path('create-dummy-data/', views.create_dummy_data, name='create-dummy-data'),
    path('show-result/', views.show_result, name='show-result'),
    path('mine-block/', views.mine_block, name='mine-block'),
    path('start-mining/', views.start_mining, name='start-mining'),
    path('blockchain/', views.blockchain, name='blockchain'),
    path('block-info/', views.block_info, name='block-info'),
    path('sync-block/', views.sync_block, name='sync-block'),
    path('verify-block/', views.verify_block, name='verify-block'),
    path('track-server/', views.track_server, name='track-server'),
    # API to expose Aadhaar Excel data
    path('api/aadhaar/', views.aadhaar_from_excel, name='aadhaar-from-excel'),
]