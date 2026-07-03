import { spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import {
  chmodSync,
  copyFileSync,
  existsSync,
  mkdirSync,
  readFileSync,
  readdirSync,
  rmSync,
  writeFileSync
} from 'node:fs'
import { dirname, join } from 'node:path'

const PYTHON_EMBED_VERSION = '3.13.14'
const PYTHON_STANDALONE_MINOR = '3.13'

const updateArgs = [
  '--update',
  'maafw',
  '--update',
  'runtime:mfa'
]
const invocation = resolveCreateMaaProject()

const result = spawnSync(
  invocation.command,
  [
    ...invocation.args,
    ...updateArgs
  ],
  {
    cwd: process.cwd(),
    stdio: 'inherit',
    shell: invocation.shell
  }
)

if (result.error) {
  throw result.error
}
if (result.status !== 0) {
  process.exit(result.status ?? 1)
}

if (existsSync('pyproject.toml')) {
  if (runtimePlatformAll()) {
    console.warn(
      '[WARN] Skipping Python Agent release runtime sync because Agent release dependencies are platform-specific. Set CREATE_MAA_PROJECT_RUNTIME_PLATFORM=<os>-<arch> to sync them.'
    )
  } else {
    await syncPythonRuntime()
  }
}

function resolveCreateMaaProject() {
  const override = process.env.CREATE_MAA_PROJECT_BIN?.trim()
  if (override) {
    return {
      command: override,
      args: [],
      shell: true
    }
  }

  const localBin = findLocalGeneratorBin()
  if (localBin) {
    return {
      command: process.execPath,
      args: [
        localBin
      ],
      shell: false
    }
  }

  return {
    command: 'pnpm',
    args: [
      'dlx',
      'create-maa-project@latest'
    ],
    shell: process.platform === 'win32'
  }
}

function findLocalGeneratorBin() {
  let dir = process.cwd()
  for (let depth = 0; depth < 6; depth += 1) {
    const bin = join(dir, 'dist', 'index.js')
    if (existsSync(bin) && packageName(dir) === 'create-maa-project') {
      return bin
    }
    const parent = dirname(dir)
    if (parent === dir) break
    dir = parent
  }
  return undefined
}

function runtimePlatformAll() {
  const value =
    process.env.CREATE_MAA_PROJECT_RUNTIME_PLATFORM?.trim() ||
    process.env.CREATE_MAA_PROJECT_PLATFORM?.trim() ||
    ''
  return value.toLowerCase() === 'all'
}

function packageName(dir) {
  try {
    return JSON.parse(readFileSync(join(dir, 'package.json'), 'utf8')).name
  } catch {
    return undefined
  }
}

async function syncPythonRuntime() {
  if (!existsSync('requirements.txt')) {
    throw new Error('requirements.txt is missing; run create-maa-project --update python-deps')
  }
  const platform = detectRuntimePlatform()
  console.log(`Synchronizing Python Agent release runtime for ${platform}...`)
  if (platform.startsWith('linux-')) {
    syncLinuxPythonDeps(platform)
  } else if (platform.startsWith('win-')) {
    await syncWindowsPythonRuntime(platform)
  } else if (platform.startsWith('osx-')) {
    await syncMacosPythonRuntime(platform)
  } else {
    throw new Error(`Unsupported Python runtime platform: ${platform}`)
  }
  console.log('Python Agent release runtime synchronized.')
}

function syncLinuxPythonDeps(platform) {
  const depsPath = `.create-maa-project/runtime/python-deps/${platform}`
  rmSync(depsPath, { recursive: true, force: true })
  mkdirSync(depsPath, { recursive: true })
  run('python', [
    '-m',
    'pip',
    'download',
    '--requirement',
    'requirements.txt',
    '--dest',
    depsPath,
    '--only-binary=:all:',
    ...linuxWheelPlatformArgs(platform)
  ])
}

async function syncWindowsPythonRuntime(platform) {
  const arch = platform.endsWith('-arm64') ? 'arm64' : 'amd64'
  const filename = `python-${PYTHON_EMBED_VERSION}-embed-${arch}.zip`
  const url = `https://www.python.org/ftp/python/${PYTHON_EMBED_VERSION}/${filename}`
  const archivePath = await downloadToCache(url, filename)
  const root = pythonRuntimeRoot(platform)
  rmSync(root, { recursive: true, force: true })
  mkdirSync(root, { recursive: true })
  extractZipWithPython(archivePath, root)
  patchWindowsPythonPth(root)
  installRequirementsIntoEmbeddedPython(platform)
}

async function syncMacosPythonRuntime(platform) {
  const asset = await resolveMacosPythonAsset(platform)
  const archivePath = await downloadToCache(asset.url, asset.name, asset.sha256)
  const root = pythonRuntimeRoot(platform)
  rmSync(root, { recursive: true, force: true })
  mkdirSync(root, { recursive: true })
  extractPythonTarWithPython(archivePath, root)
  ensureEmbeddedPythonExecutable(platform)
  installRequirementsIntoEmbeddedPython(platform)
}

function installRequirementsIntoEmbeddedPython(platform) {
  const python = embeddedPythonExecutable(platform)
  if (!existsSync(python)) {
    throw new Error(`Embedded Python executable is missing after extraction: ${python}`)
  }
  run('uv', [
    'pip',
    'install',
    '--python',
    python,
    '--system',
    '--requirement',
    'requirements.txt'
  ])
}

function ensureEmbeddedPythonExecutable(platform) {
  const python = embeddedPythonExecutable(platform)
  if (existsSync(python)) {
    chmodSync(python, 0o755)
    return
  }
  if (!platform.startsWith('osx-')) {
    throw new Error(`Embedded Python executable is missing after extraction: ${python}`)
  }

  const binDir = join(pythonRuntimeRoot(platform), 'bin')
  const candidate = findPythonExecutableCandidate(binDir)
  if (!candidate) {
    throw new Error(`Embedded Python executable is missing after extraction: ${python}`)
  }
  copyFileSync(join(binDir, candidate), python)
  chmodSync(python, 0o755)
}

function findPythonExecutableCandidate(binDir) {
  if (!existsSync(binDir)) return undefined
  for (const name of [
    'python3.13',
    'python3.13t',
    'python'
  ]) {
    if (existsSync(join(binDir, name))) return name
  }
  return readdirSync(binDir).find((name) => /^python3(?:\.\d+)?$/.test(name))
}

async function resolveMacosPythonAsset(platform) {
  const response = await fetchGithubJson(
    'https://api.github.com/repos/astral-sh/python-build-standalone/releases/latest'
  )
  if (
    !isRecord(response) ||
    typeof response.tag_name !== 'string' ||
    !Array.isArray(response.assets)
  ) {
    throw new Error('Invalid python-build-standalone release payload.')
  }
  const tag = response.tag_name
  const platformTriple = platform === 'osx-arm64' ? 'aarch64-apple-darwin' : 'x86_64-apple-darwin'
  const pattern = new RegExp(
    `^cpython-${escapeRegExp(PYTHON_STANDALONE_MINOR)}\\.\\d+\\+${escapeRegExp(tag)}-${escapeRegExp(platformTriple)}-install_only_stripped\\.tar\\.gz$`
  )
  for (const asset of response.assets) {
    if (!isRecord(asset) || typeof asset.name !== 'string') continue
    if (!pattern.test(asset.name)) continue
    if (typeof asset.browser_download_url !== 'string') {
      throw new Error(`Python release asset has no download URL: ${asset.name}`)
    }
    const sha256 =
      typeof asset.digest === 'string' ? parseGithubSha256Digest(asset.digest) : undefined
    if (!sha256) {
      throw new Error(`Python release asset has no sha256 digest: ${asset.name}`)
    }
    return {
      name: asset.name,
      url: asset.browser_download_url,
      sha256
    }
  }
  throw new Error(`No Python ${PYTHON_STANDALONE_MINOR} runtime asset found for ${platform}`)
}

async function fetchGithubJson(url) {
  const headers = {
    Accept: 'application/vnd.github+json',
    'X-GitHub-Api-Version': '2022-11-28'
  }
  const token = process.env.GH_TOKEN?.trim() || process.env.GITHUB_TOKEN?.trim()
  if (token) headers.Authorization = `Bearer ${token}`
  const response = await fetch(url, { headers })
  if (!response.ok) {
    throw new Error(`Failed to resolve GitHub release ${url}: HTTP ${response.status}`)
  }
  return response.json()
}

async function downloadToCache(url, filename, expectedSha256) {
  const cacheDir = '.create-maa-project/cache'
  mkdirSync(cacheDir, { recursive: true })
  const target = join(cacheDir, filename)
  console.log(`Downloading ${url}`)
  const response = await fetch(url)
  if (!response.ok) {
    throw new Error(`Failed to download ${url}: HTTP ${response.status}`)
  }
  const content = Buffer.from(await response.arrayBuffer())
  if (expectedSha256) {
    const actual = sha256(content)
    if (actual !== expectedSha256) {
      throw new Error(
        `Checksum mismatch for ${filename}: expected ${expectedSha256}, got ${actual}`
      )
    }
  }
  writeFileSync(target, content)
  return target
}

function extractZipWithPython(archivePath, target) {
  runPythonScript(
    `
import pathlib
import sys
import zipfile

archive = sys.argv[1]
target = pathlib.Path(sys.argv[2])
with zipfile.ZipFile(archive) as zip_file:
    zip_file.extractall(target)
`,
    [
      archivePath,
      target
    ]
  )
}

function extractPythonTarWithPython(archivePath, target) {
  runPythonScript(
    `
import os
import pathlib
import shutil
import sys
import tarfile

archive = sys.argv[1]
target = pathlib.Path(sys.argv[2])

with tarfile.open(archive, "r:gz") as tar:
    members = [member for member in tar.getmembers() if member.isfile()]
    roots = {member.name.split("/", 1)[0] for member in members if member.name}
    strip_root = len(roots) == 1 and all("/" in member.name for member in members)
    for member in members:
        name = member.name.replace("\\\\", "/")
        if strip_root:
            name = name.split("/", 1)[1]
        if name.startswith("python/"):
            name = name[len("python/"):]
        if name.startswith("install/"):
            name = name[len("install/"):]
        if not name or name.endswith("/"):
            continue
        lower = name.lower()
        if lower == ".ds_store" or lower.endswith("/.ds_store") or lower.startswith("__macosx/"):
            continue
        destination = target / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        source = tar.extractfile(member)
        if source is None:
            continue
        with source, destination.open("wb") as handle:
            shutil.copyfileobj(source, handle)
        os.chmod(destination, member.mode & 0o777)
`,
    [
      archivePath,
      target
    ]
  )
}

function patchWindowsPythonPth(root) {
  const pth = readdirSync(root).find((entry) => /^python\d*\._pth$/i.test(entry))
  if (!pth) {
    throw new Error(`Windows embedded Python runtime is missing python*._pth in ${root}`)
  }
  const path = join(root, pth)
  const lines = readFileSync(path, 'utf8').replace(/\r\n/g, '\n').split('\n')
  while (lines.at(-1)?.trim() === '') lines.pop()
  const next = lines.map((line) => {
    const trimmed = line.trim()
    return trimmed === '#import site' || trimmed === '# import site' ? 'import site' : line
  })
  if (!next.some((line) => line.trim() === 'import site')) next.push('import site')
  for (const item of [
    '.',
    'Lib',
    'Lib\\site-packages',
    'DLLs'
  ]) {
    if (!next.some((line) => line.trim() === item)) next.push(item)
  }
  writeFileSync(path, `${next.join('\n')}\n`, 'utf8')
}

function runPythonScript(script, args) {
  run('python', [
    '-c',
    script,
    ...args
  ])
}

function run(command, args) {
  const child = spawnSync(command, args, {
    cwd: process.cwd(),
    stdio: 'inherit',
    shell: false
  })
  if (child.error) {
    throw child.error
  }
  if (child.status !== 0) {
    throw new Error(`Command failed: ${command} ${args.join(' ')} (exit code ${child.status ?? 1})`)
  }
}

function detectRuntimePlatform() {
  const explicit =
    process.env.CREATE_MAA_PROJECT_RUNTIME_PLATFORM?.trim() ||
    process.env.CREATE_MAA_PROJECT_PLATFORM?.trim()
  if (explicit) {
    const normalized = normalizeRuntimePlatform(explicit)
    if (!normalized || normalized === 'all') {
      throw new Error(`Unsupported runtime platform: ${explicit}`)
    }
    return normalized
  }
  if (process.env.GITHUB_ACTIONS === 'true') {
    throw new Error(
      'Runtime platform must be explicit in GitHub Actions. Set CREATE_MAA_PROJECT_RUNTIME_PLATFORM from the workflow matrix, for example win-arm64.'
    )
  }
  const os =
    process.platform === 'win32'
      ? 'win'
      : process.platform === 'darwin'
        ? 'osx'
        : process.platform === 'linux'
          ? 'linux'
          : ''
  const arch = normalizeRuntimeArch(process.arch)
  if (!os || !arch) {
    throw new Error('release runtime platform could not be detected')
  }
  return `${os}-${arch}`
}

function normalizeRuntimePlatform(value) {
  const normalized = String(value)
    .trim()
    .toLowerCase()
    .replace(/^windows/, 'win')
    .replace(/^win32/, 'win')
    .replace(/^darwin/, 'osx')
    .replace(/^macos/, 'osx')
    .replace(/x86_64/g, 'x64')
    .replace(/amd64/g, 'x64')
    .replace(/aarch64/g, 'arm64')
    .replace(/_/g, '-')
  if (normalized === 'all') return 'all'
  return /^(win|linux|osx)-(x64|arm64)$/.test(normalized) ? normalized : ''
}

function normalizeRuntimeArch(value) {
  if (value === 'x64' || value === 'x86_64' || value === 'amd64') return 'x64'
  if (value === 'arm64' || value === 'aarch64') return 'arm64'
  return ''
}

function linuxWheelPlatformArgs(platform) {
  const tags = platform === 'linux-arm64' ? [
          'manylinux_2_28_aarch64',
          'manylinux_2_17_aarch64',
          'manylinux2014_aarch64',
          'linux_aarch64'
        ] : [
          'manylinux_2_28_x86_64',
          'manylinux_2_17_x86_64',
          'manylinux2014_x86_64',
          'linux_x86_64'
        ]
  return tags.flatMap((tag) => [
    '--platform',
    tag
  ])
}

function pythonRuntimeRoot(platform) {
  return `.create-maa-project/runtime/python/${platform}`
}

function embeddedPythonExecutable(platform) {
  return platform.startsWith('win-')
    ? `.create-maa-project/runtime/python/${platform}/python.exe`
    : `.create-maa-project/runtime/python/${platform}/bin/python3`
}

function sha256(content) {
  return createHash('sha256').update(content).digest('hex')
}

function parseGithubSha256Digest(value) {
  const match = /^sha256:([a-f0-9]{64})$/i.exec(value.trim())
  return match?.[1]?.toLowerCase()
}

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

function isRecord(value) {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}
