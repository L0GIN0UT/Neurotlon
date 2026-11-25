import { useEffect, useState } from 'react'
import { Icon } from './Icon.tsx'
import { Notice } from './Notice.tsx'
import { EEG_METHODS } from './eegMethods.ts'
import { Select } from './Select.tsx'
import type { SelectOption } from './Select.tsx'
import * as t from './texts.ts'
import type { Command, SensorDevice, SetupFields, StateView } from './types.ts'

type SetupState = Extract<StateView, { kind: 'setup' }>

/** Сколько секунд осталось поиску: считает окно, ядро присылает только «идёт» и «закончил». */
function useScanCountdown(scanning: boolean, seconds: number): number {
  const [left, setLeft] = useState(seconds)
  useEffect(() => {
    if (!scanning) return
    const started = Date.now()
    const tick = () => setLeft(Math.max(0, Math.ceil(seconds - (Date.now() - started) / 1000)))
    const timer = setInterval(tick, 250)
    return () => clearInterval(timer)
  }, [scanning, seconds])
  return scanning ? left : seconds
}

function modeOptions(current: string): SelectOption[] {
  const options: SelectOption[] = [
    { value: 'hardware', label: t.SETUP.sensorsHardware },
    { value: 'emulate', label: t.SETUP.sensorsEmulate },
  ]
  // «Мост отдельно» нужен разработчику: обычному админу его не предлагаем, пока он не выбран.
  if (current === '') options.push({ value: '', label: t.SETUP.sensorsExternal })
  return options
}

/** Раздел «Датчики»: режим, поиск и серийные номера по ролям дисциплины. */
export function SensorsSection({
  state,
  fields,
  setFields,
  send,
}: {
  state: SetupState
  fields: SetupFields
  setFields: (update: (fields: SetupFields) => SetupFields) => void
  send: (command: Command) => void
}) {
  const scan = state.scan
  const scanning = scan.phase === 'scanning'
  const left = useScanCountdown(scanning, scan.seconds)
  if (!state.sensors_available) return null

  const hardware = fields.sensors === 'hardware'
  const setSerial = (role: string, serial: string) =>
    setFields((f) => ({ ...f, devices: { ...f.devices, [role]: serial } }))
  const offered = (role: string): SensorDevice[] =>
    scan.devices.filter((d) => d.kind === t.SETUP.roleKind[role] && d.serial !== '')
  const progress = scanning ? 1 - left / scan.seconds : 0

  return (
    <div className="setup-field setup-sensors">
      <span className="setup-label" id="setup-sensors-label">
        {t.SETUP.sensors}
      </span>
      <Select
        labelId="setup-sensors-label"
        value={fields.sensors}
        options={modeOptions(fields.sensors)}
        onChange={(sensors) => setFields((f) => ({ ...f, sensors }))}
      />
      <span className="setup-hint">{t.SETUP.sensorsModeHint[fields.sensors] ?? ''}</span>
      {fields.sensors !== '' && state.roles.includes('eeg') && (
        <div className="setup-field" data-testid="eeg-method">
          <span className="setup-label" id="setup-eeg-method-label">
            {t.SETUP.eegMethod}
          </span>
          <Select
            labelId="setup-eeg-method-label"
            value={fields.eeg_method}
            options={EEG_METHODS}
            onChange={(eeg_method) => setFields((f) => ({ ...f, eeg_method }))}
          />
          <span className="setup-hint">{t.SETUP.eegMethodHint[fields.eeg_method] ?? ''}</span>
        </div>
      )}
      {hardware && (
        <div className="sensors-panel">
          <div className="sensors-scan">
            <button
              type="button"
              className="setup-action scan-button"
              disabled={scanning}
              onClick={() => send({ action: 'sensors_scan' })}
            >
              {scanning ? (
                <span className="scan-spinner" aria-hidden />
              ) : (
                <Icon name="search" />
              )}
              {scanning ? t.SETUP.sensorsScanning : scan.phase === 'done' ? t.SETUP.sensorsRescan : t.SETUP.sensorsScan}
            </button>
            {scanning && (
              <span className="scan-left" data-testid="scan-left">
                {t.SETUP.sensorsLeft(left)}
              </span>
            )}
          </div>
          {scanning && (
            <div className="scan-progress" aria-hidden>
              <span style={{ width: `${Math.round(progress * 100)}%` }} />
            </div>
          )}
          {scan.phase === 'done' && scan.error && <Notice tone="bad">{scan.error}</Notice>}
          {scan.phase === 'done' && !scan.error && scan.devices.length === 0 && (
            <Notice tone="warn" testId="sensors-none">
              <b>{t.SETUP.sensorsNone}</b>
              <ul>
                {t.SETUP.sensorsNoneTips.map((tip) => (
                  <li key={tip}>{tip}</li>
                ))}
              </ul>
            </Notice>
          )}
          {scan.devices.length > 0 && (
            <ul className="sensors-found" data-testid="sensors-found">
              {scan.devices.map((d) => (
                <li key={d.address}>
                  <b>{t.SETUP.sensorsDeviceKind[d.kind] ?? d.kind}</b> {d.name}{' '}
                  <span className="setup-hint">
                    {d.serial || t.SETUP.sensorsSerialUnknown} · {d.address}
                  </span>
                </li>
              ))}
            </ul>
          )}
          {state.roles.length === 0 ? (
            <p className="setup-hint">{t.SETUP.sensorsNeedCheck}</p>
          ) : (
            state.roles.map((role) => (
              <label key={role} className="sensors-role">
                <span>{t.SETUP.roles[role] ?? role}</span>
                <input
                  value={fields.devices[role] ?? ''}
                  placeholder={t.SETUP.sensorsSerial}
                  list={`serials-${role}`}
                  spellCheck={false}
                  autoComplete="off"
                  onChange={(event) => setSerial(role, event.target.value)}
                />
                <datalist id={`serials-${role}`}>
                  {offered(role).map((d) => (
                    <option key={d.address} value={d.serial} label={d.name} />
                  ))}
                </datalist>
              </label>
            ))
          )}
        </div>
      )}
    </div>
  )
}
