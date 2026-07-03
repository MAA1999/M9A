import { createHash } from 'node:crypto'
import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs'

const interfaceJson = JSON.parse(readFileSync('interface.json', 'utf8'))
const project = JSON.parse(readFileSync('maa-project.json', 'utf8'))
const lock = JSON.parse(readFileSync('maa-project.lock.json', 'utf8'))
const packageJson = JSON.parse(readFileSync('package.json', 'utf8'))
const imports = interfaceJson.import ?? []

if (interfaceJson.name !== project.project?.slug) {
  throw new Error('interface.json name must match maa-project.json project.slug')
}

if (interfaceJson.label !== project.project?.displayName) {
  throw new Error('interface.json label must match maa-project.json project.displayName')
}

if (interfaceJson.version !== addV(project.project?.version)) {
  throw new Error('interface.json version must match maa-project.json project.version')
}

if (interfaceJson.icon !== 'logo.ico') {
  throw new Error('interface.json icon must be logo.ico')
}

if (packageJson.name !== project.project?.slug) {
  throw new Error('package.json name must match maa-project.json project.slug')
}

if (packageJson.version !== project.project?.version) {
  throw new Error('package.json version must match maa-project.json project.version')
}

const expectedPackageLicense =
  project.license?.spdx === 'None' ? 'UNLICENSED' : project.license?.spdx
if (packageJson.license !== expectedPackageLicense) {
  throw new Error('package.json license must match maa-project.json license.spdx')
}

if (packageJson.packageManager !== 'pnpm@11.5.1') {
  throw new Error('package.json packageManager must be pnpm@11.5.1')
}

if (packageJson.engines?.node !== '>=24') {
  throw new Error('package.json engines.node must be >=24')
}

for (const [
  name,
  version
] of Object.entries(expectedDevDependencies())) {
  if (packageJson.devDependencies?.[name] !== version) {
    throw new Error(`package.json ${dependencyLabel(name)} must be pinned to ${version}`)
  }
}

for (const [
  name,
  command
] of Object.entries(expectedPackageScripts(project))) {
  if (packageJson.scripts?.[name] !== command) {
    const message =
      name === 'check:maa'
        ? 'package.json scripts.check:maa must use local pnpm exec maa-tools check'
        : `package.json scripts.${name} must be ${command}`
    throw new Error(message)
  }
}

if (!existsSync('.node-version')) {
  throw new Error('.node-version is missing')
}

if (readFileSync('.node-version', 'utf8').trim() !== '24') {
  throw new Error('.node-version must pin Node 24')
}

const requiredWorkflows = projectHasGithubAutomation(project) ? [
      '.github/workflows/check.yml',
      '.github/workflows/release.yml'
    ] : []
if (project.addons?.schemaSync) {
  requiredWorkflows.push('.github/workflows/schema-sync.yml')
}
if (project.addons?.optimizeImages) {
  requiredWorkflows.push('.github/workflows/optimize-images.yml')
}
for (const workflow of requiredWorkflows) {
  if (!existsSync(workflow)) {
    throw new Error(`${workflow} is missing`)
  }
  if (!workflowPinsNode24(readFileSync(workflow, 'utf8'))) {
    throw new Error(`${workflow} must use Node 24 in actions/setup-node`)
  }
}

if (project.features?.vscode?.enabled) {
  if (!existsSync('.vscode/settings.json')) {
    throw new Error('.vscode/settings.json is missing')
  }

  const vscodeSettings = JSON.parse(readFileSync('.vscode/settings.json', 'utf8'))
  if (vscodeSettings['editor.formatOnSave'] !== true) {
    throw new Error('.vscode/settings.json editor.formatOnSave must be true')
  }

  if (vscodeSettings['files.eol'] !== '\n') {
    throw new Error('.vscode/settings.json files.eol must be LF')
  }

  if (!hasJsoncFileAssociations(vscodeSettings['files.associations'])) {
    throw new Error('.vscode/settings.json files.associations must map *.json and *.jsonc to jsonc')
  }

  for (const language of [
    '[json]',
    '[jsonc]'
  ]) {
    if (editorDefaultFormatter(vscodeSettings[language]) !== 'esbenp.prettier-vscode') {
      throw new Error(
        `.vscode/settings.json ${language} editor.defaultFormatter must be esbenp.prettier-vscode`
      )
    }
  }

  if (!hasInterfaceJsonSchema(vscodeSettings['json.schemas'])) {
    throw new Error(
      '.vscode/settings.json json.schemas must map /interface.json to ./tools/schema/interface.schema.json'
    )
  }
}

if (
  !hasPending(lock, 'node-deps') &&
  typeof packageJson.packageManager === 'string' &&
  packageJson.packageManager.startsWith('pnpm@') &&
  !existsSync('pnpm-lock.yaml')
) {
  throw new Error('pnpm-lock.yaml is missing; run pnpm install')
}

if (existsSync('pyproject.toml')) {
  const pyprojectContent = readFileSync('pyproject.toml', 'utf8')
  const pyproject = parseTomlProjectMetadata(pyprojectContent)
  if (pyproject.name !== project.project?.slug) {
    throw new Error('pyproject.toml project.name must match maa-project.json project.slug')
  }
  if (pyproject.version !== project.project?.version) {
    throw new Error('pyproject.toml project.version must match maa-project.json project.version')
  }
  if (!tomlHasAgentWheelPackage(pyprojectContent)) {
    throw new Error('pyproject.toml hatch wheel packages must include agent')
  }
}

if (
  JSON.stringify(interfaceJson.controller ?? []) !==
  JSON.stringify(interfaceController(projectControllerKinds(project)))
) {
  throw new Error('interface.json controller must match maa-project.json controller.kinds')
}

if (interfaceJson.agent !== undefined && !Array.isArray(interfaceJson.agent)) {
  throw new Error('interface.json agent must be an array')
}

if (JSON.stringify(interfaceJson.agent) !== JSON.stringify(interfaceAgent(project))) {
  throw new Error('interface.json agent must match maa-project.json python config')
}

const resources = interfaceResources(interfaceJson.resource)
if (!Array.isArray(interfaceJson.resource) || resources[0]?.path?.[0] !== './resource/base') {
  throw new Error('interface.json resource must start with ./resource/base')
}

const expectedResources = interfaceResourceItems(project.resources ?? [])
if (JSON.stringify(resources) !== JSON.stringify(expectedResources)) {
  throw new Error('interface.json resource order differs from maa-project.json resources')
}

const expectedResourcePaths = (project.resources ?? []).map((pack) => './' + pack.path)
if (!existsSync('maatools.config.mts')) {
  throw new Error('maatools.config.mts is missing')
}

const maatoolsConfigContent = readFileSync('maatools.config.mts', 'utf8')
if (maatoolsConfigContent.includes('defineConfig')) {
  throw new Error('maatools.config.mts must not use @nekosu/maa-tools defineConfig')
}
if (!hasMaatoolsRequiredFields(maatoolsConfigContent)) {
  throw new Error(
    "maatools.config.mts must set maaVersion, interfacePath: 'interface.json', and check: {}"
  )
}
const maatoolsResources = parseMaatoolsResourceArray(maatoolsConfigContent)
if (
  !maatoolsResources ||
  JSON.stringify(maatoolsResources) !== JSON.stringify(expectedResourcePaths)
) {
  throw new Error('maatools.config.mts resource order differs from maa-project.json resources')
}

for (const path of [
  ...interfaceResourcePaths(interfaceJson.resource),
  ...imports
]) {
  if (typeof path !== 'string' || path.includes('\\')) {
    throw new Error('interface/import paths must be strings with forward slashes')
  }
  if (!existsSync(path)) {
    throw new Error(`referenced path does not exist: ${path}`)
  }
}

for (const path of walkJsonFiles([
  'interface.json',
  'tasks',
  'resource'
])) {
  const content = readFileSync(path, 'utf8')
  if (content.includes('\\')) {
    throw new Error(`MaaFW JSON paths must use forward slashes: ${path}`)
  }
}

for (const [
  path,
  state
] of Object.entries(lock.managedFiles ?? {})) {
  if (!existsSync(path)) {
    throw new Error(`managed file is missing: ${path}`)
  }
  const hash = managedFileHash(path, readFileSync(path))
  if (hash !== state.hash) {
    throw new Error(`managed file changed since last accepted baseline: ${path}`)
  }
  if (state.acceptedAt) {
    console.warn('[INFO] Managed file has accepted local changes: ' + path)
    console.warn('       Future template updates may conflict with this file.')
  }
}

for (const item of lock.pending ?? []) {
  console.error(`[ERR] Pending ${item.kind}: ${item.command}`)
}

if ((lock.pending ?? []).length > 0) {
  throw new Error('project has pending actions; run create-maa-project --doctor')
}

console.log('[OK] project structure looks valid')

function sha256(content) {
  return createHash('sha256').update(content).digest('hex')
}

function projectControllerKinds(project) {
  const rawKinds = Array.isArray(project.controller?.kinds)
    ? project.controller.kinds
    : project.controller?.kind === 'None'
      ? []
      : [
          project.controller?.kind
        ]
  const kinds = unique(rawKinds.map((kind) => normalizeControllerKind(kind)).filter(Boolean))
  return kinds.length > 0 ? kinds : [
        'Adb'
      ]
}

function normalizeControllerKind(kind) {
  if (typeof kind !== 'string') return undefined
  switch (kind.toLowerCase()) {
    case 'adb':
    case 'android':
      return 'Adb'
    case 'win32':
    case 'windows':
      return 'Win32'
    case 'macos':
    case 'mac':
      return 'MacOS'
    case 'playcover':
      return 'PlayCover'
    case 'gamepad':
      return 'Gamepad'
    case 'wlroots':
    case 'wl-roots':
      return 'WlRoots'
    default:
      return undefined
  }
}

function interfaceController(kinds) {
  return kinds.map((kind) => {
    const metadata = controllerMetadata(kind)
    return {
      name: metadata.name,
      label: metadata.label,
      type: kind,
      display_short_side: 720
    }
  })
}

function projectHasGithubAutomation(project) {
  return (
    Boolean(project.addons?.github) ||
    project.features?.ci?.enabled ||
    project.features?.release?.enabled
  )
}

function controllerMetadata(kind) {
  switch (kind) {
    case 'Adb':
      return { name: 'Android', label: 'Android / Emulator' }
    case 'Win32':
      return { name: 'Windows', label: 'Windows app' }
    case 'MacOS':
      return { name: 'macOS', label: 'macOS app' }
    case 'PlayCover':
      return { name: 'PlayCover', label: 'PlayCover iOS app' }
    case 'Gamepad':
      return { name: 'Gamepad', label: 'Gamepad (Windows)' }
    case 'WlRoots':
      return { name: 'WlRoots', label: 'wlroots app (Linux)' }
    default:
      return { name: String(kind), label: String(kind) }
  }
}

function unique(values) {
  return [
    ...new Set(values)
  ]
}

function interfaceAgent(project) {
  if (!project.python) return undefined
  const [
    childExec = '',
    ...childArgs
  ] = project.python.devCommand ?? [
    'uv',
    'run',
    'python',
    'agent/bootstrap.py'
  ]
  return [
    {
      child_exec: childExec,
      ...(childArgs.length > 0 ? { child_args: childArgs } : {}),
      identifier: project.project?.slug + '.agent'
    }
  ]
}

function interfaceResourceItems(resources) {
  return resources.map((pack) => ({
    name: pack.slug,
    label: pack.label,
    path: [
      './' + pack.path
    ]
  }))
}

function interfaceResources(value) {
  return Array.isArray(value) ? value.filter((item) => isRecord(item)) : []
}

function arrayOfStrings(value) {
  return Array.isArray(value) ? value.filter((item) => typeof item === 'string') : []
}

function interfaceResourcePaths(value) {
  return interfaceResources(value).flatMap((item) => arrayOfStrings(item.path))
}

function addV(version) {
  return String(version ?? '').startsWith('v') ? version : 'v' + version
}

function hasPending(lock, kind) {
  return (lock.pending ?? []).some((item) => item?.kind === kind)
}

function workflowPinsNode24(content) {
  return /node-version:\s*['"]?24['"]?/.test(content)
}

function editorDefaultFormatter(value) {
  if (!isRecord(value)) return undefined
  return typeof value['editor.defaultFormatter'] === 'string'
    ? value['editor.defaultFormatter']
    : undefined
}

function hasInterfaceJsonSchema(value) {
  if (!Array.isArray(value)) return false
  return value.some((item) => {
    if (!isRecord(item) || item.url !== './tools/schema/interface.schema.json') return false
    return Array.isArray(item.fileMatch) && item.fileMatch.includes('/interface.json')
  })
}

function hasJsoncFileAssociations(value) {
  return isRecord(value) && value['*.json'] === 'jsonc' && value['*.jsonc'] === 'jsonc'
}

function isRecord(value) {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function stripDotSlash(path) {
  return path.startsWith('./') ? path.slice(2) : path
}

function dependencyLabel(name) {
  return name === '@nekosu/maa-tools' ? '@nekosu/maa-tools' : 'devDependencies.' + name
}

function expectedDevDependencies() {
  return {
    '@nekosu/maa-tools': '1.0.24',
    '@nekosu/prettier-plugin-maafw-sort': '1.0.5',
    prettier: '3.8.4',
    'prettier-plugin-multiline-arrays': '4.1.9'
  }
}

function expectedPackageScripts(project) {
  const scripts = {
    format: 'prettier --write .',
    'format:check': 'prettier --check .',
    lint: 'node tools/check-project.mjs',
    'check:schema': 'node tools/validate-schema.mjs',
    'check:maa': 'pnpm exec maa-tools check',
    check: 'pnpm format:check && pnpm check:schema && pnpm check:maa && pnpm lint'
  }
  if (projectHasGithubAutomation(project)) {
    scripts['release:dry-run'] = 'node tools/build-release.mjs --dry-run'
    scripts['sync:runtime'] = 'node tools/sync-runtime.mjs'
  }
  if (project.addons?.schemaSync) {
    scripts['sync:schema'] = 'node tools/sync-schema.mjs'
  }
  if (project.addons?.optimizeImages) {
    scripts['optimize:images'] = 'node tools/optimize-images.mjs'
  }
  if (project.python) {
    scripts['format:py'] = 'uv run --frozen ruff format .'
    scripts['lint:py'] = 'uv run --frozen ruff check .'
    scripts['typecheck:py'] = 'uv run --frozen pyright'
    scripts['check:py'] = 'pnpm lint:py && pnpm typecheck:py'
  }
  return scripts
}

function managedFileHash(path, content) {
  if (isBinaryManagedPath(path)) {
    return sha256(content)
  }
  const text = content.toString()
  if (path === '.gitignore') {
    return sha256(normalizeManagedText(extractGitignoreBlock(text) ?? text))
  }
  return sha256(normalizeManagedText(text))
}

function isBinaryManagedPath(path) {
  return path.endsWith('.onnx')
}

function normalizeManagedText(content) {
  return content.replace(/\r\n?/g, '\n')
}

function extractGitignoreBlock(content) {
  const start = content.indexOf('# BEGIN create-maa-project')
  if (start < 0) return undefined
  const markerEnd = content.indexOf('# END create-maa-project', start)
  if (markerEnd < 0) return undefined
  const endOfLine = content.indexOf('\n', markerEnd)
  return content.slice(start, endOfLine >= 0 ? endOfLine + 1 : content.length)
}

function walkJsonFiles(paths) {
  const files = []
  for (const path of paths) {
    if (!existsSync(path)) continue
    const stat = statSync(path)
    if (stat.isDirectory()) {
      for (const entry of readdirSync(path)) {
        files.push(
          ...walkJsonFiles([
            `${path}/${entry}`
          ])
        )
      }
    } else if (path.endsWith('.json')) {
      files.push(path)
    }
  }
  return files
}

function parseTomlProjectMetadata(content) {
  const section = tomlProjectSection(content)
  return {
    name: parseTomlStringField(section, 'name'),
    version: parseTomlStringField(section, 'version')
  }
}

function tomlProjectSection(content) {
  const section = []
  let inside = false
  for (const line of content.split(/\r?\n/)) {
    if (/^\s*\[project\]\s*$/.test(line)) {
      inside = true
      continue
    }
    if (inside && /^\s*\[[^\]]+\]\s*$/.test(line)) break
    if (inside) section.push(line)
  }
  return section.join('\n')
}

function tomlHasAgentWheelPackage(content) {
  const section = tomlSection(content, 'tool.hatch.build.targets.wheel')
  return /^\s*packages\s*=\s*\[\s*"agent"\s*\]\s*$/.test(section)
}

function tomlSection(content, name) {
  const section = []
  let inside = false
  const pattern = new RegExp('^\\s*\\[' + escapeRegExp(name) + '\\]\\s*$')
  for (const line of content.split(/\r?\n/)) {
    if (pattern.test(line)) {
      inside = true
      continue
    }
    if (inside && /^\s*\[[^\]]+\]\s*$/.test(line)) break
    if (inside) section.push(line)
  }
  return section.join('\n')
}

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

function parseTomlStringField(section, key) {
  const match = section.match(new RegExp('^\\s*' + key + '\\s*=\\s*"([^"]*)"\\s*$', 'm'))
  return match?.[1]
}

function hasMaatoolsRequiredFields(content) {
  return (
    /\bmaaVersion\s*:\s*['"][^'"]+['"]/.test(content) &&
    /\binterfacePath\s*:\s*['"]interface\.json['"]/.test(content) &&
    /\bcheck\s*:\s*\{/.test(content)
  )
}

function parseMaatoolsResourceArray(content) {
  const match = content.match(/resource\s*:\s*(\[[^\]]*\])/)
  if (!match?.[1]) return undefined
  return [
    ...match[1].matchAll(/(['"])(.*?)\1/g)
  ].map((item) => item[2])
}
