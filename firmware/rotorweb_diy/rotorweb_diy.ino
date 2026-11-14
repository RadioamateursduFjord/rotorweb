/*
 * RotorWeb DIY — croquis Arduino (version 1.0)
 * ---------------------------------------------
 * Contrôleur de rotor « bidouille » : lit le potentiomètre du rotor et commande
 * deux relais (horaire / anti-horaire), plus deux autres en option pour l'élévation.
 * Toute la logique (calibration, cible, course, arrêt anticipé) est faite par RotorWeb
 * sur le Raspberry Pi. L'Arduino applique seulement les ordres, avec deux sécurités :
 *
 *   1. CHIEN DE GARDE : si le Raspberry Pi ne parle plus pendant 2 secondes,
 *      tous les relais sont coupés.
 *   2. TEMPS MORT : un relais ne peut pas s'enclencher moins de 500 ms après
 *      l'arrêt du sens opposé (protège le moteur et les contacts).
 *
 * Protocole série (115200 bauds, lignes terminées par \n) :
 *   P      → "P <brut_az> <brut_el>"   (0–1023, moyenne de 16 lectures)
 *   AZ+    → rotation horaire           AZ- → anti-horaire     AZ0 → arrêt azimut
 *   EL+    → monter                     EL- → descendre        EL0 → arrêt élévation
 *   S      → tout arrêter
 *   V      → "RWDIY 1.0"
 *
 * Compatible Uno, Nano, Mega. À adapter ci-dessous : broches et logique des relais.
 */

// ===== Broches (à adapter) =====
const int PIN_CW    = 4;   // relais rotation horaire (droite)
const int PIN_CCW   = 5;   // relais rotation anti-horaire (gauche)
const int PIN_UP    = 6;   // relais élévation haut   (optionnel)
const int PIN_DOWN  = 7;   // relais élévation bas    (optionnel)
const int POT_AZ    = A0;  // tension de position azimut (0–5 V)
const int POT_EL    = A1;  // tension de position élévation (optionnel)
const int PIN_LED   = 13;  // allumée quand un relais est actif

// La plupart des modules relais pour Arduino s'activent avec un niveau BAS.
const bool RELAY_ACTIVE_LOW = true;

const unsigned long WATCHDOG_MS = 2000;
const unsigned long DEADTIME_MS = 500;

// ===== Fin des réglages =====
struct AxisPins { int pos; int neg; int dir; int want; unsigned long offAt; };
AxisPins az = {PIN_CW, PIN_CCW, 0, 0, 0};
AxisPins el = {PIN_UP, PIN_DOWN, 0, 0, 0};
unsigned long lastRx = 0;
char buf[24];
byte n = 0;

void relayWrite(int pin, bool on) {
  digitalWrite(pin, (on ^ RELAY_ACTIVE_LOW) ? HIGH : LOW);
}

// Applique le sens demandé en respectant le temps mort (appelé aussi dans loop)
void applyAxis(AxisPins &a) {
  if (a.want == a.dir) return;
  if (a.dir != 0) {                  // coupe toujours avant de changer de sens
    relayWrite(a.pos, false);
    relayWrite(a.neg, false);
    a.dir = 0;
    a.offAt = millis();
  }
  if (a.want == 0) return;
  if (millis() - a.offAt < DEADTIME_MS) return;   // réessayé à la prochaine boucle
  relayWrite(a.want > 0 ? a.pos : a.neg, true);
  a.dir = a.want;
}

void setAxis(AxisPins &a, int d) {
  a.want = d;
  applyAxis(a);
}

int readAvg(int pin) {
  long s = 0;
  for (int i = 0; i < 16; i++) s += analogRead(pin);
  return (int)(s / 16);
}

void allOff() {
  setAxis(az, 0);
  setAxis(el, 0);
}

void handle(const char *c) {
  lastRx = millis();
  if (!strcmp(c, "P")) {
    Serial.print("P ");
    Serial.print(readAvg(POT_AZ));
    Serial.print(' ');
    Serial.println(readAvg(POT_EL));
  } else if (!strcmp(c, "AZ+")) { setAxis(az, 1);  Serial.println("OK"); }
  else if (!strcmp(c, "AZ-"))  { setAxis(az, -1); Serial.println("OK"); }
  else if (!strcmp(c, "AZ0"))  { setAxis(az, 0);  Serial.println("OK"); }
  else if (!strcmp(c, "EL+"))  { setAxis(el, 1);  Serial.println("OK"); }
  else if (!strcmp(c, "EL-"))  { setAxis(el, -1); Serial.println("OK"); }
  else if (!strcmp(c, "EL0"))  { setAxis(el, 0);  Serial.println("OK"); }
  else if (!strcmp(c, "S"))    { allOff();        Serial.println("OK"); }
  else if (!strcmp(c, "V"))    { Serial.println("RWDIY 1.0"); }
  else                         { Serial.println("ERR"); }
}

void setup() {
  int outs[] = {PIN_CW, PIN_CCW, PIN_UP, PIN_DOWN};
  for (int i = 0; i < 4; i++) {
    relayWrite(outs[i], false);      // état sûr AVANT de passer en sortie
    pinMode(outs[i], OUTPUT);
    relayWrite(outs[i], false);
  }
  pinMode(PIN_LED, OUTPUT);
  Serial.begin(115200);
  lastRx = millis();
}

void loop() {
  while (Serial.available()) {
    char ch = Serial.read();
    if (ch == '\n' || ch == '\r') {
      if (n) { buf[n] = 0; handle(buf); n = 0; }
    } else if (n < sizeof(buf) - 1) {
      buf[n++] = toupper(ch);
    } else {
      n = 0;                          // ligne trop longue : on jette
    }
  }
  applyAxis(az);
  applyAxis(el);
  if (millis() - lastRx > WATCHDOG_MS && (az.want || el.want || az.dir || el.dir)) {
    allOff();                         // le Raspberry Pi ne répond plus : sécurité
  }
  digitalWrite(PIN_LED, (az.dir || el.dir) ? HIGH : LOW);
}
