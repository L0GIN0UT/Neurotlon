'use strict'
// Передаёт странице адрес и токен моста. Страница больше ничего из Electron не видит.

const { contextBridge } = require('electron')

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
