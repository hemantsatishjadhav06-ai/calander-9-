from django.urls import path

from . import views_customer_workflow

urlpatterns = [
    path("workflow/", views_customer_workflow.workflow, name="workflow"),
    path("workflow/create/", views_customer_workflow.workflow_create, name="workflow_create"),
    path("workflow/status/", views_customer_workflow.workflow_status, name="workflow_status"),
    path("workflow/<uuid:conversation_id>/resume/", views_customer_workflow.workflow_resume, name="workflow_resume"),
]
