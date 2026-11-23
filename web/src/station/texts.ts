// Тексты интерфейса станции. Тексты ошибок машины (неверный ID и т. п.) приходят уже по-русски.

export const BRAND = 'Нейротлон'
export const BRAND_SUB = 'BCI Samara-2027'

export const DISCIPLINE_NAMES: Record<string, string> = {
  darts: 'Дартс',
  football: 'Футбол',
  pong: 'Понг',
}

export const STEPS = ['Бейдж', 'Проверка', 'Игра', 'Результат'] as const

export const LINK = { live: 'Связь есть', lost: 'Нет связи', unknown: 'Проверяем связь' }
export const BRIDGE_LOST = 'Нет связи с лаунчером'
export const SENSORS_DOWN = 'Датчики не подключены'

export const SCAN_PROMPT = 'Покажите QR-код бейджа камере'
export const SCAN_PROMPT_PONG = ['Игрок 1: покажите QR-код бейджа', 'Игрок 2: покажите QR-код бейджа']
export const TYPE_HINT = 'или введите номер бейджа'
export const ID_PLACEHOLDER = 'NT07'
export const NEXT = 'Далее'
export const SLOT = ['Игрок 1', 'Игрок 2']
export const SIDE = ['слева', 'справа']
export const SLOT_WAITING = 'ждём бейдж'
export const NO_CAMERA = 'Камера недоступна'
export const NO_CAMERA_HINT = 'Введите номер бейджа справа'
export const CAMERA_STARTING = 'Запускаем камеру…'

export const CHECKING = 'Проверяем участника…'
export const STARTING = 'Запускаем игру…'
export const STARTING_HINT = 'Подключаем датчики, это займёт несколько секунд'
export const PLAYING = 'Идёт игра'
export const PLAYING_HINT = 'Следуйте подсказкам на экране игры'
export const PLAYING_OFFLINE = 'Нет связи с сервером: результат отправится позже'
export const LIMIT_DEFAULT = 'Лимит очков не получен с сервера, используется 10'

export const PLAY = 'Играть'
export const PLAY_NEXT = 'Дальше'
export const NOT_ME = 'Это не я'
export const INFO = { participant: 'Участник', team: 'Команда', discipline: 'Дисциплина' }
export const TEAM_NONE = 'Команда ещё не назначена'
export const OFFLINE_WARNING = 'Нет связи с сервером: проверка не выполнена, результат отправится позже'
export const ISSUES: Record<string, string> = {
  not_checked_in: 'Нет отметки о регистрации',
  already_completed: 'Эту дисциплину уже проходил(а)',
  busy_on_other_station: 'Играет на другом стенде',
  no_pair_assigned: 'Не назначена пара',
}

export const DONE = 'Готово!'
export const POINTS_UNIT = 'очк.'

export const PROBLEM = 'Техническая проблема'
export const PROBLEM_HINT = 'Позовите волонтёра. Можно повторить игру или отметить «не пройдено».'
export const RETRY = 'Повторить'
export const GIVE_UP = 'Не пройдено'

export const BLOCKED = 'Стенд остановлен'
export const BLOCKED_CALL = 'Позовите организатора'
export const BLOCKED_HINT = 'Исправьте launcher.toml или станцию в админке и перезапустите лаунчер (Ctrl+Q)'

export const REJECTED_TITLE = 'Отклонённые результаты'
export const REJECTED_HINT = 'Покажите волонтёру или нажмите F2'
export const REJECTED_EMPTY = 'Отклонённых результатов нет'
export const REJECTED_COLUMNS = ['Сессия', 'Участники', 'Причина']
export const EXPORT = 'Экспорт в файл'
export const BACK = 'Назад'
export const exportedTo = (path: string): string => `Сохранено: ${path}`

export const QUEUE = (n: number): string => `Ждут отправки: ${n}`
export const REJECTED_CHIP = (n: number): string => `Не принято сервером: ${n}`

export const teamLine = (number: number, name: string): string => `Команда ${number}: ${name}`

/** «NT03: 8 очк.» → подпись и значение; строка без «: » целиком идёт в подпись. */
export function splitResultLine(line: string): { label: string; value: string } {
  const at = line.indexOf(': ')
  return at < 0 ? { label: line, value: '' } : { label: line.slice(0, at), value: line.slice(at + 2) }
}

export const SETUP = {
  title: 'Настройка стенда',
  lead: 'Делается один раз. Дальше стенд запускается сам и работает без админа.',
  server: 'Адрес сервера',
  serverHint: 'https://192.168.1.10',
  token: 'Токен станции',
  tokenHint: 'Скопируйте из админки при создании станции',
  tokenSaved: 'Сохранён. Оставьте пустым, чтобы не менять',
  show: 'Показать',
  hide: 'Скрыть',
  game: 'Игра (файл .exe)',
  gameHint: 'C:/Neurotlon/games/Darts/Darts.exe',
  cert: 'Сертификат зала',
  certHint: 'Необязательно. Корневой сертификат, если сервер с самоподписанным',
  browse: 'Выбрать…',
  sensors: 'Датчики',
  sensorsHardware: 'Настоящие датчики (BrainBit, Callibri)',
  sensorsEmulate: 'Эмулятор: значения клавишами, для проверки без датчиков',
  sensorsExternal: 'Мост запускаю отдельно',
  sensorsScan: 'Найти датчики',
  sensorsScanning: 'Ищем датчики (около 12 секунд)…',
  sensorsNone: 'Датчики не найдены. Проверьте питание, Bluetooth и расстояние.',
  sensorsSerialUnknown: 'серийный номер неизвестен: впишите с наклейки на корпусе',
  sensorsSerial: 'Серийный номер',
  sensorsNeedCheck: 'Нажмите «Проверить подключение»: станция сообщит, какие датчики нужны.',
  sensorsDeviceKind: { brainbit: 'BrainBit', callibri: 'Callibri' } as Record<string, string>,
  roles: {
    eeg: 'ЭЭГ (BrainBit)',
    emg: 'ЭМГ (Callibri)',
    emg_left: 'Левая рука (Callibri)',
    emg_right: 'Правая рука (Callibri)',
  } as Record<string, string>,
  roleKind: { eeg: 'brainbit', emg: 'callibri', emg_left: 'callibri', emg_right: 'callibri' } as Record<
    string,
    string
  >,
  camera: 'Камера для QR',
  cameraDefault: 'По умолчанию',
  cameraNone: 'Камеры не найдены',
  cameraMissing: 'Выбранной камеры сейчас нет, будет использована камера по умолчанию',
  check: 'Проверить подключение',
  checking: 'Проверяем…',
  save: 'Сохранить и запустить',
  saved: 'Сохранено. Запускаем стенд…',
  connected: 'Подключена станция',
  playersOne: '1 игрок',
  playersTwo: '2 игрока: слева и справа',
}
