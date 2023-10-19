// Execute custom JS for django-autocomplete-light
// after django.jQuery is defined.
// Clears subscription plan selections when the selected
// customer agreement is changed in the LicenseTransferJobAdminForm.
window.addEventListener("load", function() {
  (function($) {
    $(':input[name$=customer_agreement]').on('change', function() {
      $(':input[name=old_subscription_plan]').val(null).trigger('change');
      $(':input[name=new_subscription_plan]').val(null).trigger('change');
    });
  })(django.jQuery);
});
