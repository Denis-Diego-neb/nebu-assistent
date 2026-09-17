package com.nebula.assistant;

import android.content.Context;
import android.os.Build;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;
import org.json.JSONObject;
import java.io.File;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;
import java.security.KeyPairGenerator;
import java.security.KeyStore;
import java.security.PrivateKey;
import java.security.Signature;
import java.security.spec.ECGenParameterSpec;
import java.util.UUID;

/** Chave privada permanece no Android Keystore; PIN nunca sai do telefone. */
final class PhoneUnlock {
    private static final String ALIAS = "nebula.windows.unlock.v1";
    private static final String TARGET = "3c541588-dcd9-4272-9046-f71a390ac7e8";

    static void prepare(Context context) throws Exception {
        KeyStore store = KeyStore.getInstance("AndroidKeyStore");
        store.load(null);
        if (!store.containsAlias(ALIAS)) {
            KeyPairGenerator generator = KeyPairGenerator.getInstance("EC", "AndroidKeyStore");
            KeyGenParameterSpec.Builder spec = new KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_SIGN)
                    .setAlgorithmParameterSpec(new ECGenParameterSpec("secp256r1"))
                    .setDigests(KeyProperties.DIGEST_SHA256)
                    .setUserAuthenticationRequired(true);
            if (Build.VERSION.SDK_INT >= 30) {
                spec.setUserAuthenticationParameters(5, KeyProperties.AUTH_DEVICE_CREDENTIAL);
            } else {
                spec.setUserAuthenticationValidityDurationSeconds(5);
            }
            generator.initialize(spec.build());
            generator.generateKeyPair();
        }
        // Exportação pública local para pareamento por USB durante a instalação.
        try (FileOutputStream out = new FileOutputStream(new File(context.getFilesDir(), "unlock-public.der"))) {
            out.write(store.getCertificate(ALIAS).getPublicKey().getEncoded());
        }
    }

    static JSONObject sign() throws Exception {
        KeyStore store = KeyStore.getInstance("AndroidKeyStore");
        store.load(null);
        String payload = "nebula-unlock-v1\n" + TARGET + "\n" + (System.currentTimeMillis() / 1000L)
                + "\n" + UUID.randomUUID().toString();
        byte[] bytes = payload.getBytes(StandardCharsets.UTF_8);
        Signature signer = Signature.getInstance("SHA256withECDSA");
        signer.initSign((PrivateKey) store.getKey(ALIAS, null));
        signer.update(bytes);
        return new JSONObject().put("payload", Base64.encodeToString(bytes, Base64.NO_WRAP))
                .put("signature", Base64.encodeToString(signer.sign(), Base64.NO_WRAP));
    }
}
