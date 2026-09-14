fn main() {
    // macOS reads privacy usage descriptions from the app's Info.plist. A
    // bundled .app gets one from Tauri, but `tauri dev` runs the bare
    // executable, which has no bundle at all -- and asking EventKit for
    // access without a usage description terminates the process.
    //
    // Embedding the same plist into the binary's __TEXT,__info_plist section
    // gives the dev build a usage description too, so the permission prompt
    // works in development. Bundled builds keep using the bundle's plist.
    #[cfg(target_os = "macos")]
    {
        println!("cargo:rerun-if-changed=Info.plist");
        match std::fs::canonicalize("Info.plist") {
            Ok(path) => println!(
                "cargo:rustc-link-arg-bins=-Wl,-sectcreate,__TEXT,__info_plist,{}",
                path.display()
            ),
            // Not fatal: the bundled app still gets its plist from Tauri.
            Err(err) => println!("cargo:warning=Info.plist not embedded ({err}); calendar permission will not work in `tauri dev`"),
        }
    }

    tauri_build::build()
}
