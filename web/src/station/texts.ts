// Тексты интерфейса станции. Тексты ошибок машины (неверный ID и т. п.) приходят уже по-русски.

export const BRAND = 'Нейротлон'
export const BRAND_SUB = 'BCI Samara-2027'

export const DISCIPLINE_NAMES: Record<string, string> = {
  darts: 'Дартс',
  football: 'Футбол',
  pong: 'Понг',
}

export const STEPS = ['Бейдж', 'Проверка', 'Калибровка', 'Игра', 'Результат'] as const

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
export const PROBLEM_HINT = 'Позовите волонтёра. Можно повторить игру или вернуться назад.'
export const RETRY = 'Повторить'

export const BLOCKED = 'Стенд остановлен'
export const BLOCKED_CALL = 'Позовите организатора'
export const BLOCKED_HINT = 'Исправьте станцию в админке или откройте настройку стенда (Ctrl+Alt+S)'

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
  tokenHint:
    'Его выдаёт админка при создании станции. По токену сервер узнаёт дисциплину стенда и принимает результаты именно от него.',
  tokenSaved: 'Сохранён. Оставьте пустым, чтобы не менять',
  show: 'Показать',
  hide: 'Скрыть',
  game: 'Игра (файл .exe)',
  gameHint: 'C:/Neurotlon/games/Darts/Darts.exe',
  gameAuto: 'Подбирается по станции',
  gameAutoHint: 'Игры входят в установщик: нужная выбирается по токену станции. Файл можно указать вручную.',
  gameWillRun: 'Будет запущена игра',
  cert: 'Сертификат зала',
  certHint: 'Необязательно. Корневой сертификат, если сервер с самоподписанным',
  browse: 'Выбрать…',
  sensors: 'Датчики',
  sensorsHardware: 'Настоящие датчики',
  sensorsEmulate: 'Эмуляция (без датчиков)',
  sensorsExternal: 'Мост запущен отдельно',
  sensorsModeHint: {
    hardware: 'BrainBit и Callibri по Bluetooth: на этом ПК Bluetooth должен быть включён, датчики включены.',
    emulate: 'Сигналы подаются сами, игра проходит всё по сценарию. Для проверки установки и игр без датчиков.',
    '': 'Для разработчика: мост датчиков запускается вручную.',
  } as Record<string, string>,
  sensorsFind: 'Искать датчики',
  sensorsSearching: 'Поиск…',
  sensorsFound: (n: number): string => `найдено ${n}`,
  sensorsStop: 'Остановить',
  sensorsStopped: 'Поиск остановлен',
  sensorsAgain: 'Искать снова',
  sensorsFailed: 'Поиск не работает',
  sensorsIdle: 'Поиск не запущен',
  sensorsSearchHint: 'Список обновляется сам. Поиск остановится через минуту без нажатий.',
  sensorsWaiting: 'Пока ничего не видно: включите датчик и поднесите его к ПК.',
  sensorsNone: 'Датчики не найдены',
  sensorsNoneTips: [
    'Датчик включён (светодиод мигает) и лежит рядом с ПК.',
    'Он не подключён в настройках Bluetooth Windows: удалите его оттуда, иначе он не виден для поиска.',
    'Bluetooth на этом ПК включён.',
    'Датчик заряжен; попробуйте выключить и включить его.',
  ],
  sensorsAssigned: 'Назначены',
  sensorsFoundTitle: 'Найденные устройства',
  sensorsRoleEmpty: 'Не выбран: нажмите «Подключить» у датчика ниже',
  sensorsDisconnect: 'Отключить',
  sensorsConnect: 'Подключить',
  sensorsReplace: 'Заменить',
  sensorsPickRole: 'Для какой роли',
  sensorsSerialAfter: 'номер после подключения',
  sensorsSerialLabel: 'Номер',
  sensorsBattery: (n: number): string => `Заряд ${n}%`,
  sensorsOffline: (s: number): string => `нет в эфире ${s} с`,
  sensorsNotNeeded: 'не нужен этой станции',
  sensorsLevelHint: 'Напрягите мышцу с датчиком: полоска должна расти.',
  sensorsLevelLabel: 'Уровень сигнала мышцы',
  sensorsRssi: (bars: number, dbm: number | null): string =>
    dbm === null ? 'Уровень приёма неизвестен' : `Уровень приёма ${bars} из 4 (${dbm} дБм)`,
  sensorsLink: {
    connecting: 'Подключение…',
    failed: 'Ошибка подключения',
    lost: 'Не в эфире',
    offline: 'Не в эфире',
    idle: 'Не подключён',
    connected: 'Подключён',
    contactLost: 'Нет контакта',
    signal: 'Сигнал есть',
  },
  eegMethod: 'Метод ЭЭГ',
  eegMethodAlpha: 'Относительная альфа (способ из нейробиатлона)',
  eegMethodEmotions: 'NeuroSDK Emotions',
  eegMethodHint: {
    alpha: 'Доля альфа-ритма по затылочным каналам, шкала по калибровке с открытыми глазами.',
    emotions: 'Расслабление из библиотеки NeuroSDK Emotions.',
  } as Record<string, string>,
  sensorsNeedCheck: 'Нажмите «Проверить подключение»: станция сообщит, какие датчики нужны.',
  sensorsDeviceKind: { brainbit: 'BrainBit', callibri: 'Callibri' } as Record<string, string>,
  roles: {
    eeg: 'ЭЭГ (BrainBit)',
    emg: 'ЭМГ (Callibri)',
    emg_left: 'Датчик игрока 1 (слева)',
    emg_right: 'Датчик игрока 2 (справа)',
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

export const CALIB = {
  title: 'Калибровка датчиков',
  steps: 'Шаги калибровки',
  link: { connecting: 'Подключаем мост датчиков…', lost: 'Мост датчиков не отвечает' },
  linkLostHint: 'Проверьте, что датчики включены, и повторите. Если не помогает, позовите волонтёра.',
  getReady: 'Приготовьтесь',
  tense: 'НАПРЯГИТЕ',
  relax: 'РАССЛАБЬТЕ',
  tenseHint: 'Напрягите мышцу с датчиком',
  relaxHint: 'Расслабьте мышцу с датчиком',
  readyHint: 'Сейчас начнётся',
  baselineLook: 'Смотрите на точку, глаза открыты',
  baselineHint: 'Спокойно дышите и не двигайтесь',
  secondsShort: 'с',
  statusPending: 'Ожидает',
  statusRunning: 'Идёт',
  statusDone: 'Готово',
  statusFailed: 'Не удалось',
  failedDefault: 'Шаг не пройден',
  failedTitle: 'Калибровка не удалась',
  retry: 'Повторить',
  restart: 'Начать заново',
  stepNames: {
    emg: 'Мышца (ЭМГ)',
    eeg: 'Мозг (ЭЭГ)',
    emg_left: 'Игрок 1 (слева)',
    emg_right: 'Игрок 2 (справа)',
  } as Record<string, string>,
  stepBoth: 'Мышцы игроков',
  stepCycle: '20 секунд: напряжение и расслабление',
  stepBaseline: '12 секунд: взгляд на точку',
  trackNames: {
    eeg: 'Мозг (ЭЭГ)',
    emg: 'Мышца (ЭМГ)',
    emg_left: 'Игрок 1 (слева)',
    emg_right: 'Игрок 2 (справа)',
  } as Record<string, string>,
  player: (n: number): string => `Игрок ${n}`,
  playerSide: ['слева', 'справа'],
  checkTitle: 'Проверка сигнала',
  checkLead: 'Последние 10 секунд. Серым отмечены участки, где сигнал недействителен.',
  tipEmg: 'Резко напрягите мышцу с датчиком: должна появиться отметка',
  tipEeg: 'Расслабьтесь: линия мозга растёт',
  recalibrateMuscle: 'Перекалибровать мышцу',
  recalibrateBrain: 'Перекалибровать мозг',
  recalibratePlayer: (n: number): string => `Повторить: игрок ${n}`,
  proceed: 'Дальше к игре',
  noSignal: 'Ждём сигнал…',
  axisNow: '0 с',
  axisAgo: (s: number): string => `−${s} с`,
  burstLabel: 'отметка',
  sensorsLabel: 'Датчики',
  methodLabel: 'Метод ЭЭГ',
  sensorNames: {
    eeg: 'Датчик мозга',
    emg: 'Датчик мышцы',
    emg_left: 'Датчик игрока 1',
    emg_right: 'Датчик игрока 2',
  } as Record<string, string>,
  sensorState: {
    connected: 'подключён',
    ok: 'подключён',
    live: 'подключён',
    connecting: 'подключаем',
    searching: 'поиск',
    disconnected: 'отключён',
    lost: 'отключён',
    emulated: 'эмуляция',
  } as Record<string, string>,
  eegMethods: { alpha: 'альфа', emotions: 'Emotions' } as Record<string, string>,
}

/** Причины недействительного сигнала по протоколу моста → подписи на графике. */
export const REASONS: Record<string, string> = {
  artifact: 'артефакт',
  no_contact: 'нет контакта',
  disconnected: 'нет контакта',
  stale: 'нет данных',
  not_calibrated: 'не откалиброван',
}
export const REASON_UNKNOWN = 'нет данных'
