# -*- coding: utf-8 -*-
"""Generic job endpoints (poll + SSE stream) backed by jobman."""
from flask import Blueprint, Response, request

from ..envelope import ok, err
from .. import jobman

bp = Blueprint("jobs", __name__, url_prefix="/api/jobs")


@bp.route("", methods=["GET"])
def list_jobs():
    kind = request.args.get("kind")
    limit = int(request.args.get("limit", 50))
    return ok(jobman.list_jobs(kind=kind, limit=limit))


@bp.route("/<job_id>", methods=["GET"])
def get_job(job_id):
    j = jobman.get(job_id)
    if not j:
        return err(404, "not_found", "job 不存在")
    return ok(j)


@bp.route("/<job_id>/stream", methods=["GET"])
def stream_job(job_id):
    since = int(request.args.get("since", 0))
    headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    return Response(jobman.stream(job_id, since), mimetype="text/event-stream", headers=headers)


@bp.route("/<job_id>/cancel", methods=["POST"])
def cancel_job(job_id):
    if not jobman.cancel(job_id):
        return err(409, "not_cancellable", "job 不可取消(不存在或已结束)")
    return ok({"job_id": job_id, "status": "cancelled"})
