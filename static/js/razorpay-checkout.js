// Opens Razorpay's checkout for the order on this page. When Razorpay reports success, its
// payment id and signature are posted to EduNexa, which verifies them and asks Razorpay for the
// real amount before recording anything. The options come from a json_script block, so the
// Content-Security-Policy needs no inline script.
(function ($) {
  "use strict";

  $(function () {
    var $button = $("[data-razorpay-open]");
    var $data = $("#razorpay-options");
    var $form = $("#razorpay-result");
    if (!$button.length || !$data.length || !$form.length || typeof window.Razorpay !== "function") {
      return;
    }
    var options = JSON.parse($data.text());
    options.handler = function (result) {
      $form.find('[name="razorpay_payment_id"]').val(result.razorpay_payment_id);
      $form.find('[name="razorpay_signature"]').val(result.razorpay_signature);
      // Preserve the SDK callback's native POST and its server-side payment verification.
      $form[0].submit();
    };
    $button.on("click.edunexaCheckout", function () {
      new window.Razorpay(options).open();
    });
  });
})(jQuery);
