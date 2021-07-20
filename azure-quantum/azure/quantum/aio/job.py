##
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
##
import logging
import asyncio
import json

from typing import TYPE_CHECKING
from urllib.parse import urlparse

from azure.quantum.job import Job as SyncJob
from azure.quantum._client.models import JobDetails
from azure.storage.blob.aio import BlobClient

__all__ = ["Job"]

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from azure.quantum.aio.workspace import Workspace


class Job(SyncJob):
    """Azure Quantum Job that is submitted to a given Workspace.

    :param workspace: Workspace instance to submit job to
    :type workspace: Workspace
    :param job_details: Job details model,
            contains Job ID, name and other details
    :type job_details: JobDetails
    """

    def __init__(self, workspace: "Workspace", job_details: JobDetails):
        self.workspace = workspace
        self.details = job_details
        self.id = job_details.id
        self.results = None

    async def refresh(self):
        """Refreshes the Job's details by querying the workspace."""
        self.details = (await self.workspace.get_job(self.id)).details

    async def wait_until_completed(self, max_poll_wait_secs=30):
        """Keeps refreshing the Job's details
        until it reaches a finished status."""
        await self.refresh()
        poll_wait = 0.2
        while not self.has_completed():
            logger.debug(
                f"Waiting for job {self.id},"
                + f"it is in status '{self.details.status}'"
            )
            print(".", end="", flush=True)
            await asyncio.sleep(poll_wait)
            await self.refresh()
            poll_wait = (
                max_poll_wait_secs
                if poll_wait >= max_poll_wait_secs
                else poll_wait * 1.5
            )

    async def _download_blob(self, blob_url):
        blob_client = BlobClient.from_blob_url(blob_url)
        logger.info(
            f"Downloading blob '{blob_client.blob_name}'"
            + f"from container '{blob_client.container_name}'"
            + f"on account: '{blob_client.account_name}'"
        )

        return (await blob_client.download_blob()).readall()

    async def get_results(self):
        if self.results is not None:
            return self.results

        if not self.has_completed():
            await self.wait_until_completed()

        if not self.details.status == "Succeeded":
            raise RuntimeError(
                f'{"Cannot retrieve results as job execution failed"}'
                + f"(status: {self.details.status}."
                + f"error: {self.details.error_data})"
            )

        url = urlparse(self.details.output_data_uri)
        if url.query.find("se=") == -1:
            # output_data_uri does not contains SAS token,
            # get sas url from service
            blob_client = BlobClient.from_blob_url(
                self.details.output_data_uri
            )
            blob_uri = self.workspace._get_linked_storage_sas_uri(
                blob_client.container_name, blob_client.blob_name
            )
            payload = await self._download_blob(blob_uri)
        else:
            # output_data_uri contains SAS token, use it
            payload = await self._download_blob(self.details.output_data_uri)

        result = json.loads(payload.decode("utf8"))
        return result