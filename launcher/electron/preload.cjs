'use strict'
// Передаёт странице адрес и токен моста и диалог выбора файла. Больше страница ничего не видит.

const { contextBridge, ipcRenderer } = require('electron')

const find = (name) => {
  const prefix = `--${name}=`
  const arg = process.argv.find((item) => item.startsWith(prefix))
  return arg ? arg.slice(prefix.length) : ''
}

const port = find('bridge-port')
const token = find('bridge-token')
if (/^\d{2,5}$/.test(port) && token) {
  contextBridge.exposeInMainWorld('stationBridge', { url: `http://127.0.0.1:${port}`, token })
}

contextBridge.exposeInMainWorld('stationShell', {
  pickFile: (kind) => ipcRenderer.invoke('pick-file', kind),
})
