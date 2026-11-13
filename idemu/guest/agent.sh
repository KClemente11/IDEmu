#!/bin/ksh
# IDEmu - agente de dados do guest: recebe do host (UART1 = /dev/ser5) o estado do CAN e do GPS virtuais.
#   C <ID-hex> <dados-hex>   ->  /var/idemu/can/<ID>      (último quadro de cada ID)
#   G <sentença NMEA>        ->  /var/idemu/gps/<TIPO>    (ex.: GPGGA, GPRMC)
#   U <seq> <hex>|-          ->  /var/idemu/uds/<seq>     (resposta UDS para o gateway HSFZ emulado no shim, src/shim/hsfz.c)
#   N <comando>              ->  navbridge-inject-qnx <comando>   (aba Cluster e HUD: SHOW|LEFT|250|m|MAIN STREET, CLEAR; validado no host)
mkdir -p /var/idemu/can /var/idemu/gps /var/idemu/uds
devc-sernuke -N -u5 -E -F -b921600 -c48000000/13 0x4806A000^2,104 > /dev/null 2>&1 &
waitfor /dev/ser5 10
while read -r t a b; do
  case "$t" in
    C) echo "$b" > /var/idemu/can/$a ;;
    G) s=${a#\$}; echo "$a" > /var/idemu/gps/${s%%,*} ;;
    U) print -r -- "${b:--}" > /var/idemu/uds/$a ;;
    N) i=/var/opt/hmi/data/ID5/Plugins/NavBridge/navbridge-inject-qnx; [ -x "$i" ] || i=/var/opt/hmi/data/rw/Plugins/NavBridge/navbridge-inject-qnx
       "$i" "$a${b:+ $b}" > /var/idemu/navbridge-inject.log 2>&1 & ;;
  esac
done < /dev/ser5
