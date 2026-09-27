# Local OpenJev: verified laptop runtime

OpenJev ran locally on September 26, 2026 (America/New_York; artifacts use
September 27 UTC) on the operator's Windows 11 x64 laptop: RTX 4090 Laptop
with 16 GB VRAM, 96 GB RAM and project Python 3.12. The pinned checkpoint loaded
in BF16 with PyTorch `2.11.0+cu128`, CUDA runtime 12.8 and Transformers `5.15.0`.
Five actual local inference attempts ran: one warm-up and four decisions
across three synthetic missions. The worker was left running at
`127.0.0.1:8770` at handoff; use the `status` command below to check its current
state before starting another instance.

OpenJev is AlexWortega's independent Qwen-based implementation. It is distinct
from hosted TypeSafe Jev. The existing `pollard-jev` adapter targets a pinned
NLI checkpoint, not the newer typed v5 interface. Gemini retains mission,
selected-evidence and reporting responsibilities in the Relay architecture.
Local OpenJev decisions remain advisory; this work has no robot connection.

## Recorded local run

The [runtime record](../artifacts/jev-openjev-runtime.json) captures the loaded
service, exact package versions, verified model-file hashes and individual run
references. Its final health snapshot records five requests with the worker
idle and ready. The same environment passed **727 offline tests** and
`pip check` reported no broken requirements.

The model loaded in **7.25 seconds**. Warm-up took **921 ms**; the four subsequent
mission decisions took **454–718 ms** at the provider boundary. These are a small
recorded trial, not a latency benchmark. The worker's PyTorch allocator reported
peak allocated memory of **9,544,062,464 bytes** and peak reserved memory of
**9,579,790,336 bytes** since startup; these are allocator measurements, not total
system or GPU memory measurements.

| Saved evidence | Local attempts | Provider latency | Result |
|---|---:|---|---|
| [Warm-up](../artifacts/jev-openjev-warmup.json) | 1 | 921 ms | Accepted passive monitoring on dry facts |
| [Dry monitoring](../artifacts/jev-openjev-dry_monitoring.json) | 1 | 718 ms | Accepted monitoring; unchanged frames reused local state |
| [Wet episode](../artifacts/jev-openjev-wet_episode.json) | 2 | 531 ms dry; 454 ms wet | Dry accepted; wet NLI abstained, controller held with alarm latched |
| [Conflicting observations](../artifacts/jev-openjev-conflicting.json) | 1 | 485 ms | NLI abstained, controller held with alarm latched |

The wet and conflicting cases returned `insufficient_nli_support`: their highest
entailment scores were approximately **0.111** and **0.190**, below the unchanged
**0.8** acceptance threshold. Their margins also fell below **0.15**. The local
controller preserved its alarms and required review; the model did not produce
an accepted escalation in these cases. No thresholds were tuned to make this
trial pass. This proves model execution and safe abstention handling, not hazard
classification quality or validated model accuracy.

All observations and actions were simulated. Gemini mission, evidence and
report roles remained fixtures, with **zero hosted API requests** and no
hardware actuation. Local API cost is zero; electricity and energy/carbon impact
were not measured. Existing hosted-call reservations are unaffected.

Historical preflight: an offline `Qwen2Tokenizer` check completed without
importing torch. Complete premise/hypothesis lengths were 506, 510, 507 and 507
tokens for four dry choices, and 507, 511 and 508 for three alarm/conflict choices.
The actual runtime artifacts record those same lengths, all below the
1,024-token limit, with `input_context_truncated=false`. Those lengths describe
unshared complete text pairs, not hosted billing tokens or measured GPU work.

## Exact checkpoint

| Item | Inspected value |
|---|---|
| Repository | `AlexWortega/openjev` |
| Revision | `552759daad712f1af6c4c13dabcb1e047886fc9c` |
| Checkpoint | `qwen3.5-4b-nli-v2` |
| Architecture | `Qwen3_5ForSequenceClassification` |
| Weight dtype | `bfloat16` |
| Recorded Transformers version | `5.15.0` |
| Weight file | `model.safetensors`, 9,078,635,984 bytes (about 8.46 GiB) |
| Weight SHA-256 | `f625c42c6bac1fbc03935f584d0126d096b6681bdc62d11f4a7c7f3b94bc35b3` |
| Helper | `modeling_openjev.py`, 13,789 bytes |
| Helper SHA-256 | `071670d0879963ee69600ed31f0f3d5a37bee314461709477e8ac0e25f33fd97` |
| Labels | `0=contradiction`, `1=entailment`, `2=neutral` |

The tokenizer file adds about 20 MB. The public revision API returned
`private=false`, `gated=false` and model-card license `mit`; no standalone
LICENSE path appeared in that revision. The Qwen base model separately provides
an Apache-2.0 license. These are upstream declarations, not a consolidated
license for all dependencies.
[Pinned configuration](https://huggingface.co/AlexWortega/openjev/blob/552759daad712f1af6c4c13dabcb1e047886fc9c/qwen3.5-4b-nli-v2/config.json),
[file metadata](https://huggingface.co/api/models/AlexWortega/openjev/tree/552759daad712f1af6c4c13dabcb1e047886fc9c/qwen3.5-4b-nli-v2),
[revision metadata](https://huggingface.co/api/models/AlexWortega/openjev/revision/552759daad712f1af6c4c13dabcb1e047886fc9c),
[base-model license](https://huggingface.co/Qwen/Qwen3.5-4B/blob/main/LICENSE).

## Windows preparation

Use the project `.venv` and record exact installed package versions. The
Transformers 5.15.0 package declares Python >=3.10, PyTorch >=2.5 for its torch
extra, Hugging Face Hub >=1.5,<2, tokenizers >=0.22,<=0.23, and safetensors >=0.8.
Python 3.12 fits those declared constraints. The trial above verifies this
specific pinned configuration on this laptop, not general Windows compatibility.
[Published package metadata](https://pypi.org/pypi/transformers/5.15.0/json)

Select a Windows x64 CUDA PyTorch wheel compatible with the installed NVIDIA
driver. PyTorch's Windows instructions support Python 3.10-3.14 and recommend
checking `torch.cuda.is_available()`. Verify `torch.cuda.is_bf16_supported()`,
the selected device name, driver/runtime versions and a small CUDA tensor
operation before loading weights. Do not infer the correct wheel from the
`nvidia-smi` CUDA label alone. Driver/runtime compatibility has feature limits.
[PyTorch installation](https://pytorch.org/get-started/locally/),
[NVIDIA compatibility](https://docs.nvidia.com/deploy/cuda-compatibility/minor-version-compatibility.html).

The selected runtime is PyTorch `2.11.0+cu128` with Transformers `5.15.0`.
The official CUDA 12.8 wheel index includes the CPython 3.12 Windows x64 build.
These are the versions used for the recorded Windows trial. From the repository
root, the installation commands for an existing project `.venv` are:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[jev]"
.\.venv\Scripts\python.exe -m pip install "torch==2.11.0+cu128" --index-url https://download.pytorch.org/whl/cu128
.\.venv\Scripts\python.exe -m pip install "transformers==5.15.0" "huggingface-hub==1.33.0" "tokenizers==0.22.2" "safetensors==0.8.0" "numpy==2.5.3"
```

Installation downloads packages; it is separate from the offline worker. The
recorded instance already has its dependencies and complete cached weights.
Avoid overlapping installations or model downloads. `torchvision`, `torchaudio`,
external inference servers and optional GPU kernel builds are not required by
this service.
[Official CUDA wheel index](https://download.pytorch.org/whl/cu128/torch/)

The inspected helper loads the whole model, then calls `.to(device).eval()`.
It defaults to bfloat16; it does not enable quantization or CPU/disk offloading.
Its retained vision tower contributes to storage even for text-only use.
Available VRAM must also hold activations, caches and framework allocations.
The initial preflight judged the 16 GB GPU plausible for a short, few-choice
trial. The recorded run now establishes that this bounded profile loaded and
ran, with allocator peaks reported above; larger contexts or workloads remain
unverified.

Qwen3.5's fast DeltaNet path can use optional `causal_conv1d` and `fla` packages.
Without them, Transformers uses slower, more memory-intensive PyTorch operations.
Start with the portable path and short context; do not make extra kernel builds
a Windows demo prerequisite. Do not enable remote Hub kernels or
`trust_remote_code=True` merely to suppress a performance warning.
[Transformers Qwen3.5 notes](https://huggingface.co/docs/transformers/model_doc/qwen3_5)

## Loading, network and custom code

`pollard_jev.providers.openjev.OpenJevProvider.from_local_cache(...)` uses
`snapshot_download(local_files_only=True)` at the pinned revision. It checks
the helper plus config, tokenizer, tokenizer config and single weights file,
then validates label order before executing the cached Python helper. The
factory does not download missing weights. It does not independently hash every
cached file, so verify the recorded hashes before execution.

The upstream helper calls native Transformers auto classes with a local snapshot
path and does not pass `trust_remote_code=True`; the inspected checkpoint has no
custom `auto_map`. Nevertheless, loading `modeling_openjev.py` through
`exec_module` is explicit execution of upstream Python. Its inference path uses
NumPy, PyTorch and Transformers; no hosted-inference client appears in that path.
Unused training/MLP save/load methods are not part of the Relay inference run.
[Pinned helper source](https://huggingface.co/AlexWortega/openjev/blob/552759daad712f1af6c4c13dabcb1e047886fc9c/modeling_openjev.py)

Keep acquisition separate from inference. A deliberate public-repository
download should pin the revision, select only the required files, use
`token=False`, and avoid printing any existing credential. Before starting the
inference process, set these variables **before library imports**:

```powershell
$env:HF_HUB_OFFLINE = "1"
$env:TRANSFORMERS_OFFLINE = "1"
$env:HF_HUB_DISABLE_IMPLICIT_TOKEN = "1"
$env:HF_HUB_DISABLE_TELEMETRY = "1"
$env:HF_HUB_DISABLE_UPDATE_CHECK = "1"
```

Hub ordinarily sends a stored token on some read requests and some libraries
collect telemetry. Offline mode prevents Hub HTTP requests; missing cache files
then fail locally. These settings are application controls, not proof of an
OS-level network sandbox. Windows cache symlink limitations can duplicate large
files, so allow room for cache and installation overhead.
[Hugging Face environment controls](https://huggingface.co/docs/huggingface_hub/package_reference/environment_variables)

## Start, inspect, run and stop

Run these commands from the repository root after the
complete pinned snapshot is present under `.state/openjev-cache` and its weight
hash has been verified. A `.partial` or `.incomplete` file is not a usable
checkpoint. The service verifies the reviewed helper and config hashes before
the loader executes the helper; missing files fail locally without downloading.

Start one foreground worker in a dedicated PowerShell terminal:

```powershell
.\.venv\Scripts\python.exe -m relay_gateway.jev_open_service --load-local --cache-dir .state/openjev-cache --port 8770 --max-requests 100 --max-length 1024
```

The opt-in flag is required. The worker sets offline controls before importing
the model libraries, requires CUDA with BF16 support, binds only
`127.0.0.1:8770`, and claims the port before allocating model memory. It accepts
one inference at a time and up to 100 attempts per worker; busy or exhausted
workers reject requests without retries. A restart is a deliberate new local
session. Wait for its `loaded` message before using a second terminal:

```powershell
.\.venv\Scripts\python.exe -m relay_gateway.jev_open_cli status --local --port 8770
.\.venv\Scripts\python.exe -m relay_gateway.jev_open_cli demo --local --port 8770 --mission wet_episode --output artifacts/jev-openjev-demo.json
```

`status` checks health and makes no inference request. Health reports the PID,
model, device, load time, context limit and request count; `ready=true` means the
worker loaded, not that a decision has succeeded. The CLI rejects fixture health
or an unexpected model and uses a fixed loopback address without ambient
proxies, redirects, retries or hosted fallback. `dry_monitoring` and
`conflicting` are also available mission names.

The demo uses actual local OpenJev only for supervision. Gemini mission,
evidence and report roles remain fixtures; observations and actions are
simulated, and no robot command is available. The result says
`local_openjev_with_gemini_fixtures` and lists those roles separately. A normal
`insufficient_nli_support` abstention exits 0 with review required; unavailable,
invalid or late inference produces an incomplete result and a nonzero exit.
An existing output file is refused before model work. Inspect an incomplete or
pending proof and worker health before deciding whether to run again with a
new filename. A client timeout cannot cancel GPU work already in progress.

Use Ctrl+C in the worker terminal to stop it. If it was launched in the
background, read the validated health PID, verify that it still belongs to this
project's service, then stop that process. On Windows, the project's `.venv`
launcher can create a child using its base Python executable. Accept that child
only when its parent is the exact project launcher and its executable is the
base interpreter reported by that launcher:

```powershell
$openJevHealthJson = & .\.venv\Scripts\python.exe -m relay_gateway.jev_open_cli status --local --port 8770
if ($LASTEXITCODE -ne 0) { throw "Worker health was not verified; no process stopped." }
$openJevHealth = $openJevHealthJson | ConvertFrom-Json
$openJevPid = [int]$openJevHealth.pid
if ($openJevPid -le 0) { throw "Invalid worker PID; no process stopped." }
$openJevPython = (Resolve-Path -LiteralPath .\.venv\Scripts\python.exe).Path
$openJevBasePythonJson = & $openJevPython -c 'import json, sys; print(json.dumps(sys._base_executable))'
if ($LASTEXITCODE -ne 0) { throw "Project interpreter was not verified; no process stopped." }
$openJevBasePython = (Resolve-Path -LiteralPath ($openJevBasePythonJson | ConvertFrom-Json)).Path
$openJevProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $openJevPid"
if (-not $openJevProcess -or $openJevProcess.CommandLine -notmatch '(?:^|\s)-m\s+relay_gateway\.jev_open_service(?:\s|$)') {
    throw "PID does not run the exact service module; no process stopped."
}
$openJevMatchesProject = $openJevProcess.ExecutablePath -ieq $openJevPython
if (-not $openJevMatchesProject) {
    $openJevParent = Get-CimInstance Win32_Process -Filter "ProcessId = $($openJevProcess.ParentProcessId)"
    $openJevMatchesProject = ($openJevProcess.ExecutablePath -ieq $openJevBasePython -and $null -ne $openJevParent -and $openJevParent.ExecutablePath -ieq $openJevPython)
}
if (-not $openJevMatchesProject) {
    throw "PID does not match this project's service; no process stopped."
}
Stop-Process -Id $openJevPid
```

Stopping a busy worker makes its in-flight result unknown. Restart with the
same foreground command only after that process has exited. These instructions
do not start a persistent background loop or a hosted API fallback.

## Interpretation and measurement

The adapter serializes structured observations and calls
`predict_hypotheses(premise, hypotheses)`. Each hypothesis produces its own
three-class probability distribution. Entailment scores across actions are not
a categorical action distribution or a calibrated probability of physical
success. The pinned helper shares the text prefix when there are at least
three hypotheses; one or two use its ordinary batched path. The recorded trial
exercised the shared-prefix path with three and four hypotheses. The one/two
hypothesis path has not been verified by these laptop artifacts.

Record load time separately from inference, model/helper hashes, actual device
and dtype, context limit, number of choices, tokenization/truncation evidence,
warm-up policy, latency and peak allocated/reserved VRAM. Shortening context can
discard meaningful evidence; a completed forward pass alone is not a correct
hazard decision. Keep malformed outputs and late answers on the safe-hold path.
Native compute may continue until it returns unless a separate worker is
terminated; a caller timeout is not GPU cancellation.

Local inference has no hosted token invoice. Electricity and energy/carbon
impact remain unmeasured; do not report them as zero. These laptop trials
demonstrate local model execution on synthetic text observations, not
Raspberry Pi performance, physical inspection, leak identification or a working
robot. Existing cloud reservations remain unresolved until independently
reconciled; a local run does not release them.
