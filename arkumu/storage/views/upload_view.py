import logging
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.urls import reverse

# Import views from their respective modules

from arkumu.storage.views.upload_views import upload_form as presigned_upload_form
from arkumu.users.mixins import general_login_required

logger = logging.getLogger(__name__)



@general_login_required
def upload_form(request):
    """
    Use the presigned upload form directly (single PUT and multipart).
    """
    logger.info(f"User {request.user.username} accessing upload form, using presigned upload")
    return presigned_upload_form(request)



@general_login_required
def upload_success(request):
    """
    Render the upload success page.
    
    This is a simple view that renders the success confirmation template.
    No business logic is performed here.
    """
    return render(request, "upload/upload_success.html")
