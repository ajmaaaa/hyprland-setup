/*
    Map country codes to ' ISO 639_ISO 3166' language codes, so we can use the system's keyboard layouts with the virtual keyboard
    The keyboard layout isn't detected under Wayland, so I'm still not sure if that's a good idea.

    Available layouts   -> https://doc.qt.io/qt-6/qtvirtualkeyboard-layouts.html
    Language labels     -> https://en.wikipedia.org/wiki/IETF_language_tag

    https://github.com/qt/qtvirtualkeyboard/blob/16fbddbbc03777e0a006daa998eda14624d62268/src/virtualkeyboard/configure.cmake
    https://github.com/qt/qtvirtualkeyboard/blob/16fbddbbc03777e0a006daa998eda14624d62268/tests/manual/x11vkbtest/testlanguagechange.cpp
    https://github.com/qt/qtvirtualkeyboard/blob/16fbddbbc03777e0a006daa998eda14624d62268/cmake/QtVirtualKeyboardSetup.cmake
*/

pragma Singleton
import QtQuick

QtObject {
    property var layouts: {
        "ar": {
            // Arabic
            "label": "Arabic",
            "kb_code": "ar_AR"
        },
        "bg": {
            // Bulgarian
            "label": "Bulgarian",
            "kb_code": "bg_BG"
        },
        "cz": {
            // Czech
            "label": "Czech",
            "kb_code": "cs_CZ"
        },
        "dk": {
            // Danish
            "label": "Danish",
            "kb_code": "da_DK"
        },
        "de": {
            // German
            "label": "German",
            "kb_code": "de_DE"
        },
        "gr": {
            // Greek
            "label": "Greek",
            "kb_code": "el_GR"
        },
        "gb": {
            "label": "British English",
            "kb_code": "en_GB"
        },
        "us": {
            "label": "American English",
            "kb_code": "en_US"
        },
        "es": {
            // Spanish
            "label": "Spanish",
            "kb_code": "es_ES"
        },
        "mx": {
            // Mexican Spanish
            "label": "Spanish (Mexico)",
            "kb_code": "es_MX"
        },
        "ee": {
            // Estonian
            "label": "Estonian",
            "kb_code": "et_EE"
        },
        "fa": {
            // Persian (Farsi)
            "label": "Persian (Farsi)",
            "kb_code": "fa_FA"
        },
        "fi": {
            // Finnish
            "label": "Finnish",
            "kb_code": "fi_FI"
        },
        "ca": {
            // Canadian French
            "label": "French (Canada)",
            "kb_code": "fr_CA"
        },
        "fr": {
            // French
            "label": "French",
            "kb_code": "fr_FR"
        },
        "il": {
            // Hebrew
            "label": "Hebrew",
            "kb_code": "he_IL"
        },
        "in": {
            // Hindi
            "label": "Hindi",
            "kb_code": "hi_IN"
        },
        "hr": {
            // Croatian
            "label": "Croatian",
            "kb_code": "hr_HR"
        },
        "hu": {
            // Hungarian
            "label": "Hungarian",
            "kb_code": "hu_HU"
        },
        "id": {
            // Indonesian
            "label": "Indonesian",
            "kb_code": "id_ID"
        },
        "it": {
            // Italian
            "label": "Italian",
            "kb_code": "it_IT"
        },
        "lv": {
            // Latvian
            "label": "Latvian",
            "kb_code": "lv_LV"
        },
        "jp": {
            // Japanese
            "label": "Japanese",
            "kb_code": "ja_JP"
        },
        "kr": {
            // Korean
            "label": "Korean",
            "kb_code": "ko_KR"
        },
        "my": {
            // Malay
            "label": "Malay",
            "kb_code": "ms_MY"
        },
        "no": {
            // Norwegian
            "label": "Norwegian",
            "kb_code": "nb_NO"
        },
        "nl": {
            // Dutch
            "label": "Dutch",
            "kb_code": "nl_NL"
        },
        "pl": {
            // Polish
            "label": "Polish",
            "kb_code": "pl_PL"
        },
        "br": {
            // Portuguese (Brazil)
            "label": "Portuguese (Brazil)",
            "kb_code": "pt_BR"
        },
        "pt": {
            // Portuguese (Europe)
            "label": "Portuguese (Portugal)",
            "kb_code": "pt_PT"
        },
        "ro": {
            // Romanian
            "label": "Romanian",
            "kb_code": "ro_RO"
        },
        "ru": {
            // Russian
            "label": "Russian",
            "kb_code": "ru_RU"
        },
        "sk": {
            // Slovak
            "label": "Slovak",
            "kb_code": "sk_SK"
        },
        "si": {
            // Slovenian
            "label": "Slovenian",
            "kb_code": "sl_SI"
        },
        "al": {
            // Albanian
            "label": "Albanian",
            "kb_code": "sq_AL"
        },
        "sp": {
            // Serbian
            "label": "Serbian",
            "kb_code": "sr_SP"
        },
        "se": {
            // Swedish
            "label": "Swedish",
            "kb_code": "sv_SE"
        },
        "th": {
            // Thai
            "label": "Thai",
            "kb_code": "th_TH"
        },
        "tr": {
            // Turkish
            "label": "Turkish",
            "kb_code": "tr_TR"
        },
        "ua": {
            // Ukrainian
            "label": "Ukrainian",
            "kb_code": "uk_UA"
        },
        "vn": {
            // Vietnamese
            "label": "Vietnamese",
            "kb_code": "vi_VN"
        },
        "cn": {
            // Simplified Chinese
            "label": "Simplified Chinese",
            "kb_code": "zh_CN"
        },
        "tw": {
            // Traditional Chinese
            "label": "Traditional Chinese",
            "kb_code": "zh_TW"
        }
        // FIXME: Missing layout for "zh_HK" (HongKong Chinese). This might be yet another SDDM bug.
    }

    function getKBCodeFor(country) {
        return country && layouts[country] ? layouts[country]["kb_code"] : "";
    }

    function getLabelFor(country) {
        return country && layouts[country] ? layouts[country]["label"] : "";
    }
}
