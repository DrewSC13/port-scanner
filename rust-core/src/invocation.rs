use std::io::{self, Read};
use std::process;

pub(crate) const MAX_REQUEST_BYTES: usize = 8 * 1024 * 1024;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum Invocation {
    Help,
    RequestStdin,
}

pub(crate) const HELP_TEXT: &str = concat!(
    "Usage: rust-core --request-stdin\n",
    "\n",
    "Opciones:\n",
    "  --request-stdin  Lee una solicitud scan_request v1 completa desde stdin.\n",
    "  --help           Muestra esta ayuda y termina.\n",
);

pub(crate) fn print_error_and_exit(message: &str, exit_code: i32) -> ! {
    eprintln!("{message}");
    process::exit(exit_code);
}

pub(crate) fn parse_invocation(args: &[String]) -> Result<Invocation, String> {
    match args {
        [argument] if argument == "--help" => Ok(Invocation::Help),
        [argument] if argument == "--request-stdin" => Ok(Invocation::RequestStdin),
        [] => Err("Uso inválido: se requiere --request-stdin o --help".to_string()),
        _ => Err("Uso inválido: solo se admite --request-stdin o --help".to_string()),
    }
}

pub(crate) fn read_stdin() -> Result<String, String> {
    let stdin = io::stdin();
    let mut limited = stdin.lock().take((MAX_REQUEST_BYTES + 1) as u64);
    let mut raw_request = Vec::new();
    limited
        .read_to_end(&mut raw_request)
        .map_err(|error| format!("No se pudo leer stdin: {error}"))?;
    if raw_request.len() > MAX_REQUEST_BYTES {
        return Err(format!(
            "Solicitud demasiado grande: máximo {MAX_REQUEST_BYTES} bytes"
        ));
    }
    String::from_utf8(raw_request).map_err(|_| "La solicitud stdin no es UTF-8 válida".to_string())
}

#[cfg(test)]
mod tests {
    use super::{parse_invocation, Invocation, HELP_TEXT, MAX_REQUEST_BYTES};

    #[test]
    fn accepts_only_contractual_process_invocations() {
        let request_args = vec!["--request-stdin".to_string()];
        let help_args = vec!["--help".to_string()];

        assert_eq!(
            parse_invocation(&request_args).expect("invocación contractual"),
            Invocation::RequestStdin,
        );
        assert_eq!(
            parse_invocation(&help_args).expect("invocación informativa"),
            Invocation::Help,
        );

        for invalid in [
            vec![],
            vec!["--host".to_string(), "127.0.0.1".to_string()],
            vec!["--ports".to_string(), "80".to_string()],
            vec!["--ports-stdin".to_string()],
            vec!["--timeout".to_string(), "1".to_string()],
            vec!["--workers".to_string(), "1".to_string()],
            vec!["--unknown".to_string()],
            vec!["positional".to_string()],
            vec!["-request-stdin".to_string()],
            vec!["--request-stdin".to_string(), "--help".to_string()],
        ] {
            assert!(parse_invocation(&invalid).is_err(), "aceptó {invalid:?}");
        }
    }

    #[test]
    fn help_exposes_only_the_contractual_process_surface() {
        assert!(HELP_TEXT.contains("Usage: rust-core --request-stdin"));
        assert!(HELP_TEXT.contains("--help"));
        for historical in [
            "--host",
            "--ports",
            "--ports-stdin",
            "--timeout",
            "--workers",
        ] {
            assert!(!HELP_TEXT.contains(historical));
        }
    }

    #[test]
    fn request_limit_is_materially_bounded() {
        assert_eq!(MAX_REQUEST_BYTES, 8 * 1024 * 1024);
    }
}
