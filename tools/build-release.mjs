import {
  chmodSync,
  cpSync,
  existsSync,
  mkdirSync,
  readFileSync,
  readdirSync,
  renameSync,
  rmSync,
  statSync,
  writeFileSync
} from 'node:fs'
import { dirname, join } from 'node:path'

const dryRun = process.argv.includes('--dry-run')
const projectSlug = 'm9a'
const releaseArtifactName = 'M9A'
mkdirSync('dist', { recursive: true })

const lock = readJson('maa-project.lock.json')
for (const item of lock.pending ?? []) {
  console.error(`[ERR] Pending ${item.kind}: ${item.command}`)
}

if ((lock.pending ?? []).length > 0) {
  throw new Error('release cannot run while project has pending actions')
}

const interfaceJson = readJson('interface.json')
if (interfaceJson.name !== projectSlug) {
  throw new Error('interface.json name must match release artifact slug')
}

const sourceVersion = String(interfaceJson.version ?? '')
if (!isReleaseVersion(sourceVersion)) {
  throw new Error('interface.json version must be a release tag such as v0.1.0')
}

const releaseTag = detectReleaseTag()
if (!dryRun && !releaseTag) {
  throw new Error('release build requires a SemVer Git tag such as v0.1.0')
}

const version = releaseTag ?? sourceVersion
if (!isReleaseVersion(version)) {
  throw new Error('release tag must be a SemVer tag such as v0.1.0')
}

const runtimePlatform = detectRuntimePlatform()
const packageInterfaceJson = prepareReleaseInterface(interfaceJson, version, runtimePlatform)
const packagePaths = mfaaReleasePackagePaths(interfaceJson, runtimePlatform)

for (const path of [
  ...strings(interfaceJson.resource),
  ...strings(interfaceJson.import)
]) {
  if (path.includes('\\')) {
    throw new Error(`release paths must use forward slashes: ${path}`)
  }
  const relativePath = path.startsWith('./') ? path.slice(2) : path
  if (!existsSync(relativePath)) {
    throw new Error(`release referenced path does not exist: ${path}`)
  }
}

if (!dryRun) {
  const guiPath = mfaaGuiPath(runtimePlatform)
  if (!existsSync(guiPath)) {
    throw new Error(`release package path is missing: ${guiPath}`)
  }
  for (const path of packagePaths) {
    if (!existsSync(path)) {
      throw new Error(`release package path is missing: ${path}`)
    }
  }
  if (packageHasAgent(interfaceJson)) {
    if (hasEmbeddedPythonRuntime(runtimePlatform)) {
      const pythonPath = pythonRuntimePath(runtimePlatform)
      if (!existsSync(pythonPath)) {
        throw new Error(`release package path is missing: ${pythonPath}`)
      }
    }
  }
  prepareReleasePackage(packagePaths, packageInterfaceJson, runtimePlatform)
  smokeReleasePackage('dist/package', packagePaths, runtimePlatform)
}

const artifacts = [
  [
    'win',
    'x86_64',
    'zip'
  ],
  [
    'win',
    'aarch64',
    'zip'
  ],
  [
    'linux',
    'x86_64',
    'tar.gz'
  ],
  [
    'linux',
    'aarch64',
    'tar.gz'
  ],
  [
    'macos',
    'x86_64',
    'tar.gz'
  ],
  [
    'macos',
    'aarch64',
    'tar.gz'
  ]
].map(
  ([
    os,
    arch,
    ext
  ]) => `${releaseArtifactName}-${os}-${arch}-${version}-MFAA.${ext}`
)

for (const artifact of artifacts) {
  if (
    !new RegExp(
      '^' +
        escapeRegExp(releaseArtifactName) +
        '-(win|linux|macos)-(x86_64|aarch64)-v.+-MFAA\\.(zip|tar\\.gz)$'
    ).test(artifact)
  ) {
    throw new Error(`invalid artifact name: ${artifact}`)
  }
  console.log(`[OK] artifact name: ${artifact}`)
}

if (!existsSync('runtimes')) {
  console.warn(
    '[WARN] Runtime assets are not present yet; run pnpm sync:runtime before a real release.'
  )
}

console.log(
  dryRun
    ? `[OK] release dry-run smoke check completed for ${projectSlug}`
    : `[OK] release build placeholder completed for ${projectSlug}`
)

function readJson(path) {
  return JSON.parse(readFileSync(path, 'utf8'))
}

function writeJson(path, value) {
  writeFileSync(path, JSON.stringify(value, null, 4) + '\n', 'utf8')
}

function strings(value) {
  return Array.isArray(value) ? value.filter((item) => typeof item === 'string') : []
}

function interfaceResourcePaths(value) {
  return Array.isArray(value)
    ? value.flatMap((item) => (isRecord(item) ? strings(item.path) : []))
    : []
}

function mfaaReleasePackagePaths(interfaceJson, runtimePlatform) {
  // Current generated release layout is the MFAAvalonia profile.
  // Other runners should add their own package profile instead of sharing these paths.
  const paths = [
    'tasks',
    'resource',
    'runtimes',
    'libs/MaaAgentBinary',
    'plugins'
  ]
  if (packageHasAgent(interfaceJson)) {
    paths.push('agent', 'requirements.txt')
    if (runtimePlatform.startsWith('linux-')) {
      paths.push(linuxPythonDepsPath(runtimePlatform))
    }
  }
  return paths
}

function packageHasAgent(interfaceJson) {
  return Array.isArray(interfaceJson.agent) && interfaceJson.agent.length > 0
}

function prepareReleaseInterface(interfaceJson, version, runtimePlatform) {
  const releaseInterface = { ...interfaceJson, version }
  delete releaseInterface.$schema
  if (packageHasAgent(interfaceJson)) {
    releaseInterface.agent = interfaceJson.agent.map((agent) =>
      isRecord(agent)
        ? {
            ...agent,
            child_exec: releaseAgentChildExec(runtimePlatform),
            child_args: releaseAgentChildArgs()
          }
        : agent
    )
  }
  return releaseInterface
}

function prepareReleasePackage(packagePaths, interfaceJson, runtimePlatform) {
  rmSync('dist/package', { recursive: true, force: true })
  mkdirSync('dist/package', { recursive: true })
  copyDirectoryContents(mfaaGuiPath(runtimePlatform), 'dist/package')
  renameMfaaEntrypoint('dist/package', runtimePlatform)
  writeJson('dist/package/interface.json', interfaceJson)
  if (existsSync('logo.ico')) {
    copyPath('logo.ico', join('dist/package', 'logo.ico'))
  }
  for (const path of packagePaths) {
    copyPath(path, join('dist/package', releasePackagePath(path)))
  }
  if (packageHasAgent(interfaceJson) && hasEmbeddedPythonRuntime(runtimePlatform)) {
    copyPath(pythonRuntimePath(runtimePlatform), join('dist/package', 'python'))
  }
  ensureUnixExecutablePermissions('dist/package', runtimePlatform)
}

function smokeReleasePackage(root, packagePaths, runtimePlatform) {
  if (!existsSync(join(root, 'interface.json'))) {
    throw new Error('release package smoke failed: interface.json is missing at package root')
  }
  const entrypoint = mfaaEntrypointName(runtimePlatform)
  if (!existsSync(join(root, entrypoint))) {
    throw new Error(`release package smoke failed: GUI entrypoint is missing: ${entrypoint}`)
  }
  if (existsSync(join(root, 'MFAAvalonia')) || existsSync(join(root, 'MFAAvalonia.exe'))) {
    throw new Error('release package smoke failed: MFAAvalonia entrypoint must be renamed')
  }
  if (existsSync(join(root, projectSlug, 'interface.json'))) {
    throw new Error(
      'release package smoke failed: package must not contain a top-level wrapper directory'
    )
  }
  for (const path of packagePaths) {
    const packagePath = releasePackagePath(path)
    if (!existsSync(join(root, packagePath))) {
      throw new Error(`release package smoke failed: package path is missing: ${packagePath}`)
    }
  }
  for (const path of releaseDevPaths()) {
    if (existsSync(join(root, path))) {
      throw new Error(`release package smoke failed: package includes dev file: ${path}`)
    }
  }

  const packagedInterface = readJson(join(root, 'interface.json'))
  if (!isRecord(packagedInterface)) {
    throw new Error('release package smoke failed: interface.json must be an object')
  }
  if (packagedInterface.$schema !== undefined) {
    throw new Error('release package smoke failed: package interface.json must not include $schema')
  }
  if (!isReleaseVersion(String(packagedInterface.version ?? ''))) {
    throw new Error(
      'release package smoke failed: package interface.json version must be a release tag'
    )
  }
  if (packageHasAgent(packagedInterface)) {
    const childExec = releaseAgentChildExec(runtimePlatform)
    if (
      hasEmbeddedPythonRuntime(runtimePlatform) &&
      !existsSync(join(root, ...childExec.split('/')))
    ) {
      throw new Error(
        `release package smoke failed: Agent Python entrypoint is missing: ${childExec}`
      )
    }
    if (!existsSync(join(root, 'agent', 'bootstrap.py'))) {
      throw new Error('release package smoke failed: Agent bootstrap is missing')
    }
  }
  assertUnixExecutablePermissions(root, runtimePlatform)
  for (const path of [
    ...interfaceResourcePaths(packagedInterface.resource),
    ...strings(packagedInterface.import)
  ]) {
    if (path.includes('\\')) {
      throw new Error(`release package smoke failed: package path uses backslashes: ${path}`)
    }
    const relativePath = path.startsWith('./') ? path.slice(2) : path
    if (!existsSync(join(root, relativePath))) {
      throw new Error(`release package smoke failed: referenced path is missing: ${path}`)
    }
  }
}

function releaseDevPaths() {
  return [
    '.github',
    '.vscode',
    '.create-maa-project',
    '.venv',
    'cache',
    'debug',
    'package.json',
    'pnpm-lock.yaml',
    'pnpm-workspace.yaml',
    'maa-project.json',
    'maa-project.lock.json',
    'tools/schema'
  ]
}

function copyPath(source, target) {
  mkdirSync(dirname(target), { recursive: true })
  cpSync(source, target, { recursive: true, force: true })
}

function copyDirectoryContents(source, target) {
  mkdirSync(target, { recursive: true })
  for (const entry of readdirSync(source)) {
    copyPath(join(source, entry), join(target, entry))
  }
}

function ensureUnixExecutablePermissions(root, runtimePlatform) {
  if (runtimePlatform.startsWith('win-')) return
  for (const path of findUnixExecutableFiles(root)) {
    const mode = statSync(path).mode
    chmodSync(path, mode | 0o755)
  }
}

function assertUnixExecutablePermissions(root, runtimePlatform) {
  if (runtimePlatform.startsWith('win-')) return
  for (const path of findUnixExecutableFiles(root)) {
    if ((statSync(path).mode & 0o111) === 0) {
      throw new Error(`release package smoke failed: executable bit is missing: ${path}`)
    }
  }
}

function findUnixExecutableFiles(root) {
  const names = new Set([
    projectSlug,
    'MFAAvalonia',
    'MaaPiCli',
    'MaaAgentServer',
    'maa-cli',
    'python',
    'python3'
  ])
  const found = []
  walkFiles(root, (path, name) => {
    if (names.has(name)) found.push(path)
  })
  return found
}

function walkFiles(root, visit) {
  for (const entry of readdirSync(root, { withFileTypes: true })) {
    const path = join(root, entry.name)
    if (entry.isDirectory()) {
      walkFiles(path, visit)
    } else if (entry.isFile()) {
      visit(path, entry.name)
    }
  }
}

function releasePackagePath(path) {
  return path.startsWith('.create-maa-project/runtime/python-deps/') ? 'deps' : path
}

function mfaaGuiPath(runtimePlatform) {
  return join('.create-maa-project', 'runtime', 'mfaa', runtimePlatform)
}

function pythonRuntimePath(runtimePlatform) {
  return join('.create-maa-project', 'runtime', 'python', runtimePlatform)
}

function linuxPythonDepsPath(runtimePlatform) {
  return join('.create-maa-project', 'runtime', 'python-deps', runtimePlatform)
}

function hasEmbeddedPythonRuntime(runtimePlatform) {
  return runtimePlatform.startsWith('win-') || runtimePlatform.startsWith('osx-')
}

function mfaaEntrypointName(runtimePlatform) {
  return runtimePlatform.startsWith('win-') ? `${projectSlug}.exe` : projectSlug
}

function renameMfaaEntrypoint(root, runtimePlatform) {
  const target = join(root, mfaaEntrypointName(runtimePlatform))
  const candidates = runtimePlatform.startsWith('win-') ? [
        'MFAAvalonia.exe',
        'MFAAvalonia'
      ] : [
        'MFAAvalonia',
        'MFAAvalonia.exe'
      ]
  for (const candidate of candidates) {
    const source = join(root, candidate)
    if (existsSync(source)) {
      renameSync(source, target)
      return
    }
  }
}

function detectRuntimePlatform() {
  const explicit = normalizeRuntimePlatform(process.env.CREATE_MAA_PROJECT_RUNTIME_PLATFORM ?? '')
  if (explicit) return explicit
  const os =
    process.platform === 'win32'
      ? 'win'
      : process.platform === 'darwin'
        ? 'osx'
        : process.platform === 'linux'
          ? 'linux'
          : ''
  const arch = normalizeRuntimeArch(process.arch)
  const platform = os && arch ? `${os}-${arch}` : ''
  if (!platform) {
    throw new Error('release runtime platform could not be detected')
  }
  return platform
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
  return /^(win|linux|osx)-(x64|arm64)$/.test(normalized) ? normalized : ''
}

function normalizeRuntimeArch(value) {
  if (value === 'x64' || value === 'x86_64' || value === 'amd64') return 'x64'
  if (value === 'arm64' || value === 'aarch64') return 'arm64'
  return ''
}

function releaseAgentChildExec(runtimePlatform) {
  if (runtimePlatform.startsWith('win-')) return 'python/python.exe'
  if (runtimePlatform.startsWith('osx-')) return 'python/bin/python3'
  return 'python3'
}

function releaseAgentChildArgs() {
  return [
    '-u',
    'agent/bootstrap.py'
  ]
}

function isRecord(value) {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function detectReleaseTag() {
  const refName = process.env.GITHUB_REF_NAME
  if (typeof refName === 'string' && refName.startsWith('v')) return refName
  const ref = process.env.GITHUB_REF
  return typeof ref === 'string' && ref.startsWith('refs/tags/')
    ? ref.slice('refs/tags/'.length)
    : undefined
}

function isReleaseVersion(value) {
  return /^v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?$/.test(value)
}

function escapeRegExp(value) {
  return value.replace(/[.*+?^${|}()|[\]\\]/g, '\\$&')
}
