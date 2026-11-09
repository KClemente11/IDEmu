# Celular conectado ao iDrive (2026-11-07)

O que existe: o celular entra pelo Wi-Fi, na mesma rede do Mac, e vira a **tela, o toque, o rotor e os botões** da head unit, e o **GPS do carro** (a posição do celular move o GPS virtual, que o HMI lê). O que não existe: Bluetooth, CarPlay, Android Auto e USB do celular. A head unit emulada não tem rádio nem controlador USB; CarPlay e Android Auto precisariam de USB com iAP2/AOA e de licenças da Apple e do Google.

## Como usar

1. Inicie um ambiente. Na aba **Celular** (tela Execução), clique em **Ligar a conexão do celular**.
2. A aba mostra um PIN de 6 dígitos e dois endereços: `http://<IP do Mac>:8766/` (controle) e `https://<IP do Mac>:8767/` (controle e GPS).
3. No celular, abra o endereço e digite o PIN. A página mostra a tela do carro ao vivo (toque e arraste na imagem tocam na tela), o rotor (arraste em círculo, ou ◀ ▶), PUSH, as setas e os botões MENU, BACK, OPTION, CD, RADIO, TEL e NAV.
4. Para o GPS, abra o endereço **HTTPS** e aceite o aviso do certificado (autoassinado, só seu) uma vez: sem HTTPS o navegador do celular bloqueia a localização. Ligue "Usar minha localização como GPS do carro".
5. Desligue na mesma aba quando terminar.

## Segurança

* O servidor principal do IDEmu continua só em `127.0.0.1`. O do celular é outro, ligado à rede local só enquanto você deixar ligado.
* PIN aleatório a cada vez, sessão por cookie (`HttpOnly`, `SameSite=Strict`), bloqueio de 60 s depois de 5 PINs errados por endereço.
* Lista fixa de rotas: `/`, `/login`, `/p/state`, `/p/screen.png`, `/p/input`, `/p/gps`. Nada de SSH, arquivos, coding, logs ou ambientes.
* O tráfego em HTTP não é criptografado: use uma rede em que você confia. Pelo HTTPS o certificado é gerado em `idemu/data/phone/` (chave com permissão 600) e refeito quando o IP do Mac muda.

## Como funciona

* `idemu/phone.py`: `PhoneLink` (dois `ThreadingHTTPServer`, o segundo com TLS), `idemu/web/phone.html` (a página do celular, sem dependências), rotas `GET /api/phone`, `POST /api/phone/start|stop` no servidor local (`docs/API.md`).
* Tela: o celular pede `/p/screen.png?since=<seq>` e o servidor segura a resposta até haver quadro novo (PNG, sem polling rápido).
* Toque: coordenadas normalizadas (0 a 1) viram pixels do display da head unit e chamam `rt.touch`, o mesmo caminho do clique na interface do Mac.
* GPS: cada posição vira `GpsSim.set(lat, lon, speed_kmh, heading, hdop)` no modo manual; o HMI recebe pelo NMEA virtual como com qualquer rota. O iDrive 8 não tem GPS virtual: o celular serve só como controle.

Testes: `tests/test_phone.py` (PIN, bloqueio, rotas, entrada, GPS, HTTPS, certificado).
