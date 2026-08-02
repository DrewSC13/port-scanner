use std::fmt;

#[derive(Debug)]
pub(crate) enum EngineError {
    RuntimeBuild(String),
    TaskJoin(String),
    ResultChannelClosed,
    WriterPanicked,
    Output(String),
    Incomplete { emitted: usize, expected: usize },
}

impl fmt::Display for EngineError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::RuntimeBuild(detail) => {
                write!(
                    formatter,
                    "No se pudo iniciar el runtime Rust asíncrono: {detail}"
                )
            }
            Self::TaskJoin(detail) => {
                write!(
                    formatter,
                    "Error interno en una tarea de escaneo Rust: {detail}"
                )
            }
            Self::ResultChannelClosed => {
                formatter.write_str("Canal de resultados Rust cerrado inesperadamente")
            }
            Self::WriterPanicked => formatter.write_str("Error interno en el hilo de salida Rust"),
            Self::Output(detail) => formatter.write_str(detail),
            Self::Incomplete { emitted, expected } => {
                write!(
                    formatter,
                    "Streaming incompleto: {emitted} de {expected} resultados"
                )
            }
        }
    }
}

impl std::error::Error for EngineError {}

#[cfg(test)]
mod tests {
    use super::EngineError;

    #[test]
    fn incomplete_error_preserves_existing_diagnostic() {
        let error = EngineError::Incomplete {
            emitted: 3,
            expected: 5,
        };
        assert_eq!(error.to_string(), "Streaming incompleto: 3 de 5 resultados");
    }
}
