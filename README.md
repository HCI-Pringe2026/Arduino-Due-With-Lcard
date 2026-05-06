# Arduino Due two-channel DAC generator

Комплект превращает два выхода Arduino Due (`DAC0`, `DAC1`) в простой
двухканальный генератор сигналов для просмотра в LGraph/LGraph2 через
LCard E14-140-M-D.

Python используется на ПК для двух задач:

- загрузить прошивку через `arduino-cli`;
- менять форму, частоту, амплитуду и фазу DAC0/DAC1 по USB Serial.

## Подключение

1. `Arduino Due GND` -> `E14 AGND`.
2. `Arduino Due DAC0` -> вход `X1` E14 в режиме с общей землей.
3. `Arduino Due DAC1` -> вход `X2` E14 в режиме с общей землей.

Не подавайте на входы Due больше 3.3 В. Выходы DAC0/DAC1 у Arduino Due не
rail-to-rail: ожидаемый диапазон около `0.55..2.75 В`. Поэтому максимальная
амплитуда около `2.20 Vpp` при смещении около `1.65 В`.

## Установка

На ПК с Windows:

```powershell
py -m pip install -r requirements.txt
```

## Загрузка прошивки

Вариант через Python:

```powershell
py tools\due_upload.py --port COM7
```

Скрипт вызывает `arduino-cli`, ставит ядро `arduino:sam`, компилирует и
загружает:

```text
firmware\due_dac_selftest\due_dac_selftest.ino
```

Если `arduino-cli` не найден, установите Arduino IDE 2.x или Arduino CLI и
передайте путь явно:

```powershell
py tools\due_upload.py --arduino-cli "C:\Program Files\Arduino IDE\resources\app\lib\backend\resources\arduino-cli.exe" --port COM7
```

Вариант вручную через Arduino IDE тоже остается: открыть скетч, выбрать
`Arduino Due (Programming Port)`, порт `COMx`, нажать `Upload`.

## Генерация сигнала для LGraph2

Одинаковый синус на двух каналах:

```powershell
py tools\due_dac_signal.py --serial-port COM7 wave --dac both --shape sine --freq 1 --amp 1.0 --offset 1.65 --phase 0
```

Независимые настройки DAC0 и DAC1 одной синхронной командой:

```powershell
py tools\due_dac_signal.py --serial-port COM7 dual `
  --shape0 sine --freq0 1 --amp0 1.0 --offset0 1.65 --phase0 0 `
  --shape1 square --freq1 2 --amp1 0.8 --offset1 1.65 --phase1 90
```

Статическое напряжение:

```powershell
py tools\due_dac_signal.py --serial-port COM7 setv --dac0 1.00 --dac1 2.20
```

Остановить генератор:

```powershell
py tools\due_dac_signal.py --serial-port COM7 stop
```

Поддерживаемые формы:

- `sine`
- `square`
- `triangle`
- `ramp`
- `dc`

Амплитуда задается как `Vpp`. Для Due безопасный практический диапазон:

```text
offset - amp/2 >= 0.55 В
offset + amp/2 <= 2.75 В
```

Те же команды можно отправлять вручную через Serial Monitor Arduino IDE
на скорости `115200`, line ending `Newline`:

```text
PING
SET 0 4095
GEN both sine 1 1.0 1.65 0
GEN2 sine 1 1.0 1.65 0 square 2 0.8 1.65 90
STOP
```

## Ручная проверка ЦАП через LGraph2

Если нужно именно получить `PASS/FAIL`, можно запустить ручную проверку:

```powershell
py tools\due_lcard_dac_test.py --serial-port COM7
```

Скрипт выставляет коды на Arduino, а вы вводите напряжения из LGraph2:

```text
Enter measured voltages for DAC0,DAC1 in volts: 0.553,2.746
```

## Критерии PASS

Для каждого ЦАП проверяются:

- измеренное напряжение рядом с ожидаемым для кода Due;
- рост напряжения при росте кода;
- достаточный размах выходного сигнала.

Порог по умолчанию: `+-0.20 В`; при необходимости задайте
`--tolerance-v 0.30`.
