export default {
  cwd: import.meta.dirname,
  maaVersion: 'latest',
  interfacePath: 'interface.json',
  resource: [
    './resource/base'
  ],
  check: {},
  vscode: {
    agents: {
      uv: 'Maa Agent: Debug'
    }
  }
}
