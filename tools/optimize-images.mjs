import { spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs'
import { resolve, relative } from 'node:path'

const EXCLUDED_DIRECTORIES = new Set([
  '.git',
  '.hg',
  '.svn',
  '.cache',
  '.temp',
  '.venv',
  'build',
  'dist',
  'node_modules',
  'out',
  'release-assets',
  'venv'
])

try {
  main()
} catch (error) {
  console.error(error instanceof Error ? error.message : String(error))
  process.exit(1)
}

function main() {
  if (process.argv.includes('--help') || process.argv.includes('-h')) {
    printUsage()
    return
  }

  ensureOxipng()

  const targets = resolveTargets()
  const files = collectPngFiles(targets)
  if (files.length === 0) {
    console.log('No PNG images found.')
    return
  }

  let changed = 0
  let totalBefore = 0
  let totalAfter = 0

  for (const file of files) {
    const beforeHash = sha256(file)
    const beforeSize = statSync(file).size
    runOxipng([
      '-o',
      'max',
      '--fast',
      '-Z',
      '-s',
      file
    ])
    runOxipng([
      '-o',
      '2',
      '-s',
      file
    ])
    const afterSize = statSync(file).size
    const afterHash = sha256(file)

    totalBefore += beforeSize
    totalAfter += afterSize
    if (beforeHash !== afterHash) {
      changed += 1
      console.log(`${displayPath(file)}: ${formatBytes(beforeSize)} -> ${formatBytes(afterSize)}`)
    }
  }

  console.log(
    `Optimized ${changed}/${files.length} PNG image(s), saved ${formatBytes(totalBefore - totalAfter)}.`
  )
}

function printUsage() {
  console.log(`Usage: node tools/optimize-images.mjs [file-or-directory ...]

When no arguments are provided, all PNG images in the repository are scanned.
Set OPTIMIZE_IMAGE_PATHS to pass newline, comma, or space-separated targets in CI.`)
}

function ensureOxipng() {
  const result = spawnSync(
    'oxipng',
    [
      '--version'
    ],
    { encoding: 'utf8' }
  )
  if (result.error?.code === 'ENOENT') {
    throw new Error('oxipng is required. Install it from https://github.com/shssoichiro/oxipng.')
  }
  if (result.status !== 0) {
    throw new Error((result.stderr || result.stdout || 'Failed to run oxipng.').trim())
  }
}

function resolveTargets() {
  const args = process.argv.slice(2)
  if (args.length > 0) return args

  const envTargets = process.env.OPTIMIZE_IMAGE_PATHS?.trim()
  if (!envTargets) return [
      '.'
    ]

  return envTargets
    .split(/[\r\n,\s]+/)
    .map((part) => part.trim())
    .filter(Boolean)
}

function collectPngFiles(targets) {
  const files = new Map()
  for (const target of targets) {
    const absoluteTarget = resolve(process.cwd(), target)
    if (!existsSync(absoluteTarget)) {
      throw new Error(`Image optimization target does not exist: ${target}`)
    }
    for (const file of collectTargetFiles(absoluteTarget)) {
      files.set(file, file)
    }
  }
  return [
    ...files.keys()
  ].sort((left, right) => displayPath(left).localeCompare(displayPath(right)))
}

function collectTargetFiles(target) {
  const stats = statSync(target)
  if (stats.isFile()) return isPng(target) ? [
          target
        ] : []
  if (!stats.isDirectory()) return []
  return walkDirectory(target)
}

function walkDirectory(directory) {
  const files = []
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    const path = resolve(directory, entry.name)
    if (entry.isSymbolicLink()) continue
    if (entry.isDirectory()) {
      if (!EXCLUDED_DIRECTORIES.has(entry.name)) {
        files.push(...walkDirectory(path))
      }
      continue
    }
    if (entry.isFile() && isPng(path)) files.push(path)
  }
  return files
}

function isPng(path) {
  return path.toLowerCase().endsWith('.png')
}

function runOxipng(args) {
  const result = spawnSync('oxipng', args, { stdio: 'inherit' })
  if (result.error) throw result.error
  if (result.status !== 0) {
    throw new Error(`oxipng failed with exit code ${result.status}.`)
  }
}

function sha256(path) {
  return createHash('sha256').update(readFileSync(path)).digest('hex')
}

function displayPath(path) {
  return relative(process.cwd(), path).replaceAll('\\', '/')
}

function formatBytes(bytes) {
  const sign = bytes < 0 ? '-' : ''
  const value = Math.abs(bytes)
  if (value < 1024) return `${sign}${value} B`
  if (value < 1024 * 1024) return `${sign}${(value / 1024).toFixed(2)} KiB`
  return `${sign}${(value / 1024 / 1024).toFixed(2)} MiB`
}
