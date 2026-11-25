import { EEG_METHODS } from './eegMethods.ts'
import { Select } from './Select.tsx'
import type { SelectOption } from './Select.tsx'
import { SensorList } from './SensorList.tsx'
import * as t from './texts.ts'
import type { Command, SetupFields, StateView } from './types.ts'

type SetupState = Extract<StateView, { kind: 'setup' }>

function modeOptions(current: string): SelectOption[] {
  const options: SelectOption[] = [
    { value: 'hardware', label: t.SETUP.sensorsHardware },
    { value: 'emulate', label: t.SETUP.sensorsEmulate },
  ]
  // «Мост отдельно» нужен разработчику: обычному админу его не предлагаем, пока он не выбран.
  if (current === '') options.push({ value: '', label: t.SETUP.sensorsExternal })
  return options
}

/** Раздел «Датчики»: режим, метод ЭЭГ и живой список датчиков по ролям дисциплины. */
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
  if (!state.sensors_available) return null

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
      {fields.sensors === 'hardware' && <SensorList sensors={state.sensors} roles={state.roles} send={send} />}
    </div>
  )
}
