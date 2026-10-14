# Apache Tika

Use Tika for non-PDF office documents, email, and other mixed formats. It is also useful as an independent metadata extractor, but it is not the default PDF text extractor.

The local Tika distribution lives at `$HOME/.local/share/document-analysis/tika/current/`. Keep its launcher JAR and adjacent libraries together. This skill uses Tika 4.x, which requires Java 17 or later. The scripts discover the launcher beneath this directory and invoke it with Java.

Treat parse errors, encryption notices, and unsupported embedded content as findings. Tika must not be used to execute macros or external links.
