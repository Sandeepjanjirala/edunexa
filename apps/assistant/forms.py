from django import forms


class QuestionForm(forms.Form):
    question = forms.CharField(
        max_length=1000,
        strip=True,
        widget=forms.Textarea(attrs={"rows": 2, "placeholder": "Type your question…"}),
    )
    # The title of the page the panel was opened on, so "this page" means something.
    page = forms.CharField(max_length=120, required=False, widget=forms.HiddenInput)
