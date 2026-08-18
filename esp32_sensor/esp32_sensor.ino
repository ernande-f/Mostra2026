#include <Wire.h>

/*
 * ====================================================================
 * PROJETO MOSTRA 2026 - CONTROLE DE ALTA SENSIBILIDADE (LATERAL AY)
 * ====================================================================
 * Aceleração lateral pura (Esquerda / Direita) com máxima sensibilidade.
 * Pitch, Roll e Vertical (Az) ignorados conforme solicitado.
 */

int mpu_address = 0x68;
bool sensor_ativo = false;

void acordar_mpu(int addr) {
  Wire.beginTransmission(addr);
  Wire.write(0x6B);
  Wire.write(0x00); // 0 = Acorda o sensor
  byte erro = Wire.endTransmission(true);
  if (erro == 0) {
    mpu_address = addr;
    sensor_ativo = true;
  }
}

void setup() {
  Serial.begin(115200);
  delay(500);

  Wire.begin(21, 22);
  Wire.setClock(100000);
  delay(100);

  acordar_mpu(0x68);
  if (!sensor_ativo) {
    acordar_mpu(0x69);
  }

  if (sensor_ativo) {
    // Configura fundo de escala do acelerômetro para +/- 2G (máxima sensibilidade: 16384 LSB/g)
    Wire.beginTransmission(mpu_address);
    Wire.write(0x1C); // ACCEL_CONFIG
    Wire.write(0x00); // 0x00 = +/- 2g
    Wire.endTransmission(true);
  }
}

void loop() {
  int16_t raw_ay = 0;

  if (sensor_ativo) {
    // Lê o registrador do eixo Y (ACCEL_YOUT_H = 0x3D)
    Wire.beginTransmission(mpu_address);
    Wire.write(0x3D);
    byte err = Wire.endTransmission(false);

    if (err == 0) {
      Wire.requestFrom(mpu_address, 2, true);
      if (Wire.available() >= 2) {
        raw_ay = (Wire.read() << 8) | Wire.read();
      }
    }
  }

  // Converte para Gs (+/- 2G: 16384 LSB/G)
  float ay = raw_ay / 16384.0;

  // Envia aceleração lateral pura Ay
  // Exemplo: "0.14" ou "-0.25"
  Serial.println(ay, 3);

  delay(15); // ~65 Hz taxa rápida e sem atrasos
}
