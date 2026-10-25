// Generated locally from this project's native Firebase configuration.
// This file is ignored by Git because it contains app-specific Firebase settings.
import 'package:firebase_core/firebase_core.dart' show FirebaseOptions;
import 'package:flutter/foundation.dart' show TargetPlatform, defaultTargetPlatform, kIsWeb;

class DefaultFirebaseOptions {
  static FirebaseOptions get currentPlatform {
    if (kIsWeb) throw UnsupportedError('Web Firebase options are not configured for this project.');
    switch (defaultTargetPlatform) {
      case TargetPlatform.android: return android;
      case TargetPlatform.iOS: return ios;
      default: throw UnsupportedError('Firebase is not configured for this platform.');
    }
  }

  static const android = FirebaseOptions(
    apiKey: "AIzaSyD6JqaDaJI-xUwFShAjTOwd63rpNE3AJjM",
    appId: "1:1007219918966:android:63ec23733f6dc2216bf757",
    messagingSenderId: "1007219918966",
    projectId: "whatsapp-clone-7a78c",
    storageBucket: "whatsapp-clone-7a78c.appspot.com",
  );

  static const ios = FirebaseOptions(
    apiKey: "AIzaSyDxaUXWZs4Fkfo2IGbneHDSDGDrshMLYSU",
    appId: "1:1007219918966:ios:073839fdb12829046bf757",
    messagingSenderId: "1007219918966",
    projectId: "whatsapp-clone-7a78c",
    storageBucket: "whatsapp-clone-7a78c.appspot.com",
    iosBundleId: "com.tauseef.whatsappclone",
  );
}
