FROM ghcr.io/natlabrockies/alfalfa/worker@sha256:3afbad460c406d52be06b3724079ed1a5570f9f3f82f577285c07c1cb45ed23b

COPY ops/alfalfa-worker/patch_output_value.py /tmp/patch_output_value.py
RUN python3 /tmp/patch_output_value.py \
    /alfalfa/alfalfa_worker/jobs/modelica/step_run.py \
    && rm /tmp/patch_output_value.py

LABEL org.opencontainers.image.title="BACTalk Alfalfa worker"
LABEL org.opencontainers.image.version="1.0.0-output-value-fix.1"
LABEL org.opencontainers.image.source="https://github.com/NREL/alfalfa"
LABEL org.opencontainers.image.licenses="BSD-3-Clause"
LABEL com.bactalk.upstream.digest="sha256:3afbad460c406d52be06b3724079ed1a5570f9f3f82f577285c07c1cb45ed23b"
LABEL com.bactalk.patch="modelica-scalar-output-value"
