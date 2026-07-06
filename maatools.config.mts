import type { FullConfig } from '@nekosu/maa-tools'
import { extractTaskRef, parseTask } from '@nekosu/maa-tools/pm'
import type { PropSelectorResult } from '@nekosu/maa-tools/pm'

declare global {
  interface ImportMeta {
    readonly dirname: string
  }
}

const config: FullConfig = {
  cwd: import.meta.dirname,
  maaVersion: 'latest',
  interfacePath: 'interface.json',
  parser: {
    customReco: (name, param, utils) => {
      const result: PropSelectorResult[] = []
      if (name === 'MultiRecognition') {
        for (const [
          key,
          obj,
        ] of utils.parseObject(param)) {
          if (key === 'nodes') {
            for (const task of utils.parseArray(obj)) {
              if (utils.isString(task)) {
                result.push({
                  node: task,
                  type: 'taskRef',
                  missingPolicy: 'error',
                })
              }
            }
          }
        }
      } else if (name === 'ColorOCR') {
        for (const [
          key,
          obj,
        ] of utils.parseObject(param)) {
          if (key === 'TargetStageName_OCR') {
            if (utils.isString(obj)) {
              result.push({
                node: obj,
                type: 'taskRef',
                missingPolicy: 'error',
              })
            }
          }
        }
      }
      return result
    },
    customAction: function (name, param, utils) {
      const result: PropSelectorResult[] = []
      const pushTaskRef = (node: PropSelectorResult['node']) => {
        result.push({
          node,
          type: 'taskRef',
          missingPolicy: 'error',
        })
      }

      if (name === 'DisableNode') {
        for (const [
          key,
          obj,
        ] of utils.parseObject(param)) {
          if (key === 'node_name') {
            if (utils.isString(obj)) {
              pushTaskRef(obj)
            }
          }
        }
      } else if (name === 'NodeOverride') {
        for (const [, overrideNode, propNode] of utils.parseObject(param)) {
          pushTaskRef(propNode)

          if (overrideNode.type === 'object') {
            const info = parseTask(overrideNode, this)
            for (const ref of info.refs) {
              const target = extractTaskRef(ref)
              if (!target || !utils.isString(ref.location)) {
                continue
              }

              if (target === ref.location.value) {
                pushTaskRef(ref.location)
              } else {
                pushTaskRef({
                  ...ref.location,
                  value: target,
                })
              }
            }
          }
        }
      } else if (name === 'ResetCount') {
        for (const [
          key,
          obj,
        ] of utils.parseObject(param)) {
          if (key === 'nodes') {
            for (const task of utils.parseArray(obj)) {
              if (utils.isString(task)) {
                pushTaskRef(task)
              }
            }
          }
        }
      } else if (name === 'SubTask') {
        for (const [
          key,
          obj,
        ] of utils.parseObject(param)) {
          if (key === 'sub') {
            for (const task of utils.parseArray(obj)) {
              if (utils.isString(task)) {
                pushTaskRef(task)
              }
            }
          }
        }
      }
      return result
    },
  },

  check: {
    override: {
      'dynamic-image': 'ignore',
      'unknown-task': 'warning',
    },
  },

  vscode: {
    agents: {
      uv: 'Maa Agent: Debug',
    },
  },
}

export default config
