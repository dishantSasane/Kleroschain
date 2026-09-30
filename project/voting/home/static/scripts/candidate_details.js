var emailmsg1 = 'Please enter a valid Email-ID and verfiy it. Key will be sent to this Email-ID.';
var emailmsg2 = 'Please verify your Email-ID. Key will be sent to this Email-ID.';
var valid_email_pattern = /^[^ ]+@[^ ]+\.[a-z]{2,3}$/;
// NEW FEATURE: Phone OTP Verification
var valid_phone_pattern = /^[\d\s\-\+\(\)]{10,15}$/;

$(document).ready(function(){
    // Phone-first flow: show email UI but keep it locked until phone is verified
    $('#email-verification-section').addClass('verification-locked');
    // Never allow voting until email OTP success
    $('#vote-now').addClass('disabled').hide();

    $('.email-alert-msg').addClass('email-alert-msg-slide-fade-in');
    set_email_alert_msg();

    function set_email_alert_msg(){
        if( valid_email_pattern.test($('#email-input').val()) ){
            $('.email-alert-msg').html(emailmsg2);
        }
        else{
            $('.email-alert-msg').html(emailmsg1);
        }
    }

    // Email validation on input
    $('#email-input').on('input', function(){
        set_email_alert_msg();
    })

    // Email is sourced from dataset; do not allow editing here.
    $('#email-input').prop('disabled', true);

    // Send otp to email address on button click and display verification div
    $('#send-otp').click(function(){

        // Enforce phone verification first at UI level
        if($(this).hasClass('disabled')){
            showAlert('Please verify your phone number first. OTP has to be verified on your registered mobile number.', 'rgba(255, 82, 82, 0.3)', 'rgb(122, 0, 0)', 'vibrate');
            return;
        }

        if( valid_email_pattern.test($('#email-input').val()) ){
            show_loading('Please wait, OTP is being sent to your email-id.')

            $.ajax(
                {
                    type:'GET',
                    url: '/send-otp/',
                    data: {}, // server uses dataset email
                    success: function(data){
 
                        setTimeout(function(){
                            hide_loading_without_reload();
                        }, 1000);

                        if(data.success){
                            
                            $('.otp-div').removeClass('otp-verification-slide-to-bottom');
                            $('.otp-div').addClass('otp-verification-slide-from-bottom');
                            $('#otp-verfication-email').html($('#email-input').val());
                            $('.otp-verification').show();
                            $('.otp-div').show();
                            showAlert('OTP send to ' + $('#email-input').val() + '.', 'rgba(136, 255, 156, 0.3)', 'rgb(0, 128, 0)');
                        }
                        else {
                            showAlert(data.error, 'rgba(255, 82, 82, 0.3)', 'rgb(122, 0, 0)', 'vibrate');
                        }

                    }
                }
            );

        }
        else {
            $('.email-alert-msg').removeClass('email-alert-msg-slide-fade-in');
            $('.email-alert-msg').addClass('boom');
            setTimeout(function(){
                $('.email-alert-msg').removeClass('boom');
            }, 1000);
        }
    });

    // Verify OTP by entered OTP
    $('#verify').click(function(){

        show_loading('Please wait, we are verifying your email-id.')

        $.ajax(
            {
                type:'GET',
                url: '/verify-otp/',
                data: {'otp-input': $('#otp-input').val()},
                success: function(data){

                    setTimeout(function(){
                        hide_loading_without_reload();
                    }, 1500);

                    if(data.success){

                        $('.otp-div').removeClass('otp-verification-slide-from-bottom');
                        $('.otp-div').addClass('otp-verification-slide-to-bottom');
                        setTimeout(function(){
                            $('.otp-verification').hide();
                            $('.otp-div').hide();
                        }, 500);

                        $('#send-otp').hide();
                        $('#verified-badge').css('display', 'inline');
                        $('#email-input').css('text-align', 'right');
                        $('.email-alert-msg').hide();
                        
                        showAlert('Email Verified. Private key sent to your email.', 'rgba(136, 255, 156, 0.3)', 'rgb(0, 128, 0)');
                        
                        // After email verification, allow voting.
                        $('#vote-now').removeClass('disabled').show();
                    }
                    else {
                        showAlert('Wrong OTP.', 'rgba(255, 82, 82, 0.3)', 'rgb(122, 0, 0)', 'vibrate');
                    }

                }
            }
        );
    });

    // Cancel OTP verification and hide verification div
    $('#cancel-otp').click(function(){
        $('.otp-div').removeClass('otp-verification-slide-from-bottom');
        $('.otp-div').addClass('otp-verification-slide-to-bottom');
        setTimeout(function(){
            $('.otp-verification').hide();
            $('.otp-div').hide();
        }, 500);
    });

    // Phone OTP (using registered dataset number) BEFORE email OTP
    // Keep email actions disabled until phone is verified
    $('#send-otp').addClass('disabled');

    // If phone was already verified earlier, show email section immediately (handles refresh)
    var phoneVerified = ($('#verification-state').data('phone-verified') + '') === '1';
    if(phoneVerified){
        $('#email-verification-section').removeClass('verification-locked');
        $('#email-alert-msg').html(emailmsg2).show();
        $('#send-otp').removeClass('disabled');
        $('#phone-verification-section').hide();
        $('#phone-alert-msg').hide();
        // Still require email OTP before voting
        $('#vote-now').addClass('disabled').hide();
    }

    // Send phone OTP to the registered phone number (no manual input)
    $('#send-phone-otp').click(function(){
        var phoneNumber = $('#phone-input').val().trim();

        if(!phoneNumber){
            $('#phone-alert-msg').html('No phone number found for this Aadhaar.');
            $('#phone-alert-msg').show();
            showAlert('No phone number found in dataset for this Aadhaar.', 'rgba(255, 82, 82, 0.3)', 'rgb(122, 0, 0)', 'vibrate');
            return;
        }

        show_loading('Please wait, OTP is being sent to your registered phone number.');

        $.ajax({
            type: 'POST',
            url: '/send-phone-otp/',
            data: {},  // server uses registered phone_number from dataset
            success: function(data){
                setTimeout(function(){
                    hide_loading_without_reload();
                }, 1000);

                if(data.success){
                    $('#phone-otp-verification-number').html(phoneNumber);
                    $('#phone-otp-verification').fadeIn(300);
                    $('#send-phone-otp').hide();
                    showAlert('OTP sent to ' + phoneNumber + '. Please check your phone for the OTP.', 'rgba(136, 255, 156, 0.3)', 'rgb(0, 128, 0)');
                } else {
                    showAlert(data.error || 'Failed to send OTP', 'rgba(255, 82, 82, 0.3)', 'rgb(122, 0, 0)', 'vibrate');
                }
            },
            error: function(){
                hide_loading_without_reload();
                showAlert('Error sending OTP. Please try again.', 'rgba(255, 82, 82, 0.3)', 'rgb(122, 0, 0)', 'vibrate');
            }
        });
    });
    
    // NEW FEATURE: Phone OTP Verification - Verify phone OTP
    $('#verify-phone-otp').click(function(){
        var otpInput = $('#phone-otp-input').val().trim();
        
        if(!otpInput || otpInput.length !== 6) {
            showAlert('Please enter a valid 6-digit OTP', 'rgba(255, 82, 82, 0.3)', 'rgb(122, 0, 0)', 'vibrate');
            return;
        }
        
        show_loading('Please wait, we are verifying your phone number.');
        
        $.ajax({
            type: 'POST',
            url: '/verify-phone-otp/',
            data: {'phone-otp-input': otpInput},
            success: function(data){
                setTimeout(function(){
                    hide_loading_without_reload();
                }, 1500);
                
                if(data.success){
                    $('#phone-otp-verification').fadeOut(300);
                    $('#phone-verification-section').slideUp(300);
                    $('#phone-alert-msg').hide();
                    // Enable email OTP flow after phone is verified
                    $('#send-otp').removeClass('disabled');
                    // Show email verification UI (robust against CSS/display issues)
                    if($('#email-verification-section').length){
                        $('#email-verification-section').removeClass('verification-locked');
                        $('#email-verification-section').stop(true, true).css('display', 'block').hide().fadeIn(200);
                    }
                    if($('#email-alert-msg').length){
                        $('#email-alert-msg').html(emailmsg2).show();
                    }
                    // Keep vote disabled until email verified
                    $('#vote-now').addClass('disabled');
                    showAlert('Phone number verified successfully. Please verify your email to receive the private key.', 'rgba(136, 255, 156, 0.3)', 'rgb(0, 128, 0)');
                    // Bring email section into view
                    try{
                        $('html, body').animate({ scrollTop: ($('#email-verification-section').offset().top - 80) }, 300);
                    }catch(e){}
                } else {
                    showAlert(data.error || 'Invalid OTP', 'rgba(255, 82, 82, 0.3)', 'rgb(122, 0, 0)', 'vibrate');
                }
            },
            error: function(){
                hide_loading_without_reload();
                showAlert('Error verifying OTP. Please try again.', 'rgba(255, 82, 82, 0.3)', 'rgb(122, 0, 0)', 'vibrate');
            }
        });
    });
    
    // NEW FEATURE: Phone OTP Verification - Cancel phone OTP
    $('#cancel-phone-otp').click(function(){
        $('#phone-otp-verification').fadeOut(300);
        $('#phone-input').prop('disabled', false);
        $('#send-phone-otp').show();
        $('#phone-otp-input').val('');
    });

    $('#vote-now').click(function(event){
        // NEW FEATURE: Phone OTP Verification - Check if button is disabled
        if($(this).hasClass('disabled')){
            showAlert('Please complete phone and email verification before voting.', 'rgba(255, 82, 82, 0.3)', 'rgb(122, 0, 0)', 'vibrate');
            return;
        }

        show_loading('Loading voting options...');

        $.ajax(
            {
                type:'GET',
                url: '/get-parties/',
                data: 'None',
                success: function(data){
                    if(data.error){
                        hide_loading_without_reload();
                        showAlert(data.error, 'rgba(255, 82, 82, 0.3)', 'rgb(122, 0, 0)', 'vibrate');
                        // If backend says email verification is required, force-show email section
                        if(data.email_verification_required){
                            if($('#email-verification-section').length){
                                $('#email-verification-section').stop(true, true).css('display', 'block').show();
                            }
                            $('#email-alert-msg').show();
                            $('#send-otp').removeClass('disabled');
                            $('#vote-now').addClass('disabled');
                            try{
                                $('html, body').animate({ scrollTop: ($('#email-verification-section').offset().top - 80) }, 300);
                            }catch(e){}
                        }
                        return;
                    }

                    parties_list_json = data.parties;
                    $('.main-content').html(data.html);

                    hide_loading();

                    showAlert('Make your choice. Remember you are going to select a new Representative.', 'rgba(201, 136, 255, 0.3)', 'rgb(102, 0, 128)');
                },
                error: function(){
                    hide_loading_without_reload();
                    showAlert('Error loading parties. Please try again.', 'rgba(255, 82, 82, 0.3)', 'rgb(122, 0, 0)', 'vibrate');
                }
            }
        );
    });

});