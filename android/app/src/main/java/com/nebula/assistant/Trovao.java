package com.nebula.assistant;

import java.util.Random;

/** Trovão sintetizado na hora, com a receita do hub (modo_chuva.sintetizar_trovao). */
final class Trovao {
    static final int TAXA = 16000;

    private Trovao() { }

    /** Estalo (raio perto) e ronco grave que some aos poucos, em PCM mono de 16 bits. */
    static short[] sintetizar(long semente, double intensidade) {
        intensidade = Math.max(0, Math.min(1, intensidade));
        Random sorteio = new Random(semente);
        double duracao = 3.0 + 4.0 * intensidade;
        int total = (int) (duracao * TAXA);
        double[][] rajadas = new double[3 + (int) (4 * intensidade)][3];
        for (double[] rajada : rajadas) {
            rajada[0] = sorteio.nextDouble() * duracao * 0.55;
            rajada[1] = 0.3 + sorteio.nextDouble() * 0.9;
            rajada[2] = 0.4 + sorteio.nextDouble() * 0.6;
        }
        double ataque = 0.02 + (1 - intensidade) * 0.25, queda = 0.9 + 1.8 * intensidade;
        // Ronco grave para o corpo e uma faixa de 90 a 450 Hz para o trovão
        // aparecer no alto-falante pequeno do celular.
        double corteAlto = 1 - Math.exp(-2 * Math.PI * 450 / TAXA);
        double corteBaixo = 1 - Math.exp(-2 * Math.PI * 90 / TAXA);
        double[] amostras = new double[total];
        double marrom = 0, grave = 0, agudo = 0, medio = 0, pico = 0;
        int bloco = TAXA / 100;
        for (int comeco = 0; comeco < total; comeco += bloco) {
            double t = (double) comeco / TAXA;
            double envelope = Math.min(1, t / ataque) * Math.exp(-t / queda);
            for (double[] rajada : rajadas) {
                double d = (t - rajada[0]) / rajada[1];
                if (d >= 0 && d < 4) envelope += 0.6 * rajada[2] * Math.exp(-d) * Math.min(1, d * 8);
            }
            boolean estalo = intensidade > 0.7 && t < 0.4;
            for (int i = comeco; i < Math.min(total, comeco + bloco); i++) {
                double branco = sorteio.nextDouble() * 2 - 1;
                marrom = (marrom + 0.02 * branco) * 0.998;
                grave += (marrom - grave) * 0.05;
                agudo += (branco - agudo) * corteAlto;
                medio += (branco - medio) * corteBaixo;
                double valor = (grave * 2.5 + (agudo - medio) * 4.0) * envelope;
                if (estalo) valor += 0.3 * intensidade * branco * Math.exp(-((double) i / TAXA) / 0.08);
                amostras[i] = valor;
                pico = Math.max(pico, Math.abs(valor));
            }
        }
        double escala = 0.6 * (0.5 + 0.5 * intensidade) / (pico == 0 ? 1 : pico) * 32767;
        short[] pcm = new short[total];
        for (int i = 0; i < total; i++) pcm[i] = (short) Math.max(-32767, Math.min(32767, amostras[i] * escala));
        return pcm;
    }
}
