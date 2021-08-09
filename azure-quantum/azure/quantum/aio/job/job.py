##
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
##
import asyncio
import logging
import json

from typing import TYPE_CHECKING

from azure.quantum._client.models import JobDetails
from azure.quantum.aio.job.base_job import BaseJob, DEFAULT_TIMEOUT
from azure.quantum.aio.job.filtered_job import FilteredJob

__all__ = ["Job"]

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from azure.quantum.aio.workspace import Workspace


_log = logging.getLogger(__name__)

class Job(BaseJob, FilteredJob):
    """Azure Quantum Job that is submitted to a given Workspace.

    :param workspace: Workspace instance to submit job to
    :type workspace: Workspace
    :param job_details: Job details model,
            contains Job ID, name and other details
    :type job_details: JobDetails
    """

    def __init__(self, workspace: "Workspace", job_details: JobDetails, **kwargs):
        self.workspace = workspace
        self.details = job_details
        self.id = job_details.id
        self.results = None
    
    async def submit(self):
        """Submit a job to Azure Quantum."""
        _log.debug(f"Submitting job with ID {self.id}")
        job = await self.workspace.submit_job(self)
        self.details = job.details

    async def refresh(self):
        """Refreshes the Job's details by querying the workspace."""
        self.details = (await self.workspace.get_job(self.id)).details

    def has_completed(self) -> bool:
        """Check if the job has completed."""
        return (
            self.details.status == "Succeeded"
            or self.details.status == "Failed"
            or self.details.status == "Cancelled"
        )

    async def wait_until_completed(
        self,
        max_poll_wait_secs=30,
        timeout_secs=None,
        print_progress=True
    ) -> None:
        """Keeps refreshing the Job's details
        until it reaches a finished status.

        :param max_poll_wait_secs: Maximum poll wait time, defaults to 30
        :type max_poll_wait_secs: int, optional
        :param timeout_secs: Timeout in seconds, defaults to None
        :type timeout_secs: int, optional
        :param print_progress: Print "." to stdout to display progress
        :type print_progress: bool, optional
        :raises TimeoutError: If the total poll time exceeds timeout, raise
        """
        await self.refresh()
        poll_wait = 0.2
        total_time = 0.
        while not self.has_completed():
            if timeout_secs is not None and total_time >= timeout_secs:
                raise TimeoutError(f"The wait time has exceeded {timeout_secs} seconds.")
 
            logger.debug(
                f"Waiting for job {self.id},"
                + f"it is in status '{self.details.status}'"
            )
            if print_progress:
                print(".", end="", flush=True)
            asyncio.sleep(poll_wait)
            total_time += poll_wait
            await self.refresh()
            poll_wait = (
                max_poll_wait_secs
                if poll_wait >= max_poll_wait_secs
                else poll_wait * 1.5
            )

    async def get_results(self, timeout_secs: float=DEFAULT_TIMEOUT) -> dict:
        """Get job results by downloading the results blob from the
        storage container linked via the workspace.

        :param timeout_secs: Timeout in seconds, defaults to 300
        :type timeout_secs: int
        :raises RuntimeError: [description]
        :return: [description]
        :rtype: dict
        """
        if self.results is not None:
            return self.results

        if not self.has_completed():
            await self.wait_until_completed(timeout_secs=timeout_secs)

        if not self.details.status == "Succeeded":
            raise RuntimeError(
                f'{"Cannot retrieve results as job execution failed"}'
                + f"(status: {self.details.status}."
                + f"error: {self.details.error_data})"
            )

        payload = await self.download_data(self.details.output_data_uri)
        results = json.loads(payload.decode("utf8"))
        return results