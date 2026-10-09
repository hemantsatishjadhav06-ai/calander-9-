"""Every kind of agency job and its stages (see ``apps.studio.engine``)."""

from __future__ import annotations

from .jobtypes import blog, chat, inbox, learn, plan, report, repurpose, seo

JOB_TYPES = {module.JOB.kind: module.JOB for module in (plan, blog, chat, inbox, report, learn, repurpose, seo)}
