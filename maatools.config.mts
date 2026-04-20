import type { FullConfig } from '@nekosu/maa-tools'
import type { PropSelectorResult } from '@nekosu/maa-tools/pm'

const config: FullConfig = {
  cwd: import.meta.dirname,
  maaVersion: '5.9.2',
  interfacePath: 'assets/interface.json',
  parser: {
    customReco: (name, param, utils) => {
      const result: PropSelectorResult[] = []
      if (name === 'MultiRecognition') {
        for (const [key, obj] of utils.parseObject(param)) {
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
        for (const [key, obj] of utils.parseObject(param)) {
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
    customAction: (name, param, utils) => {
      const result: PropSelectorResult[] = []
      if (name === 'DisableNode' || name === 'ResetCount') {
        for (const [key, obj] of utils.parseObject(param)) {
          if (key === 'node_name') {
            if (utils.isString(obj)) {
              result.push({
                node: obj,
                type: 'taskRef',
                missingPolicy: 'error',
              })
            }
          }
        }
      } else if (name === 'SubTask') {
        for (const [key, obj] of utils.parseObject(param)) {
          if (key === 'sub') {
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
      }
      return result
    },
  },

  check: {
    override: {
      'dynamic-image': 'ignore',
    },
  },
}

export default config
