"""Entrada OFX limitada e publicação exclusiva de relatórios determinísticos."""
import argparse
from dataclasses import asdict
import os
from pathlib import Path
import re
import stat
import sys
import tempfile

from . import __version__
from .api import parse_ofx
from .model import Limits, OfxError
from .report import to_csv, to_json, to_markdown


class _UsageError(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise _UsageError('Argumentos inválidos. Use --help para consultar o formato aceito.')

    def _print_message(self, message, file=None):
        if message:
            if file is None or file is sys.stdout:
                _write_stdout(message)
            else:
                _diagnostic(message.rstrip('\n'))


def _positive_integer(value):
    if not re.fullmatch(r'[0-9]{1,9}', value):
        raise ValueError('Limite inválido')
    return int(value)


def _parser():
    parser = _Parser(prog='extrato-ofx', allow_abbrev=False,
                     description='Lê extratos OFX bancários e de cartão localmente, com valores exatos e cobertura explícita.')
    parser.add_argument('file', metavar='FILE', help='Arquivo OFX regular; use - para ler stdin explicitamente.')
    parser.add_argument('--version', action='version', version='extrato-ofx ' + __version__)
    parser.add_argument('--format', choices=('json', 'markdown', 'csv'), default='json')
    parser.add_argument('--output', metavar='NEW', help='Arquivo NOVO; o diretório pai já deve existir.')
    for key, value in asdict(Limits()).items():
        parser.add_argument('--' + key.replace('_', '-'), type=_positive_integer, default=value,
                            help='Limite de recursos positivo (padrão: %(default)s).')
    parser.add_argument('--allow-incomplete-csv', action='store_true', help='Exportar somente linhas interpretadas mesmo com cobertura incompleta.')
    return parser


def _read_input(source, limits):
    try:
        if source == '-':
            stream = getattr(sys.stdin, 'buffer', sys.stdin)
            raw = stream.read(limits.max_input_bytes + 1)
            if type(raw) is str:
                raw = raw.encode('utf-8')
        else:
            descriptor = os.open(source, os.O_RDONLY | getattr(os, 'O_NONBLOCK', 0)
                                 | getattr(os, 'O_CLOEXEC', 0))
            try:
                if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                    raise OfxError('input_type', 'A origem deve ser um arquivo regular; stdin exige - explícito.')
                stream = os.fdopen(descriptor, 'rb')
                descriptor = None
                with stream:
                    raw = stream.read(limits.max_input_bytes + 1)
            finally:
                if descriptor is not None:
                    os.close(descriptor)
        if type(raw) is not bytes:
            raise OfxError('input_read', 'Não foi possível ler a entrada OFX.')
        if len(raw) > limits.max_input_bytes:
            raise OfxError('input_size', 'A entrada OFX excede o limite de bytes.')
        return raw
    except (OSError, ValueError, UnicodeError) as error:
        if isinstance(error, OfxError):
            raise
        raise OfxError('input_read', 'Não foi possível ler uma entrada OFX dentro do limite.') from None


def _publish_new(destination, text):
    # Adapted from the MIT publisher in LOFRANO TECNOLOGIA's Recorrência Civil;
    # attribution and license are recorded in THIRD_PARTY_NOTICES.md.
    destination = Path(destination)
    temporary = None
    try:
        descriptor, name = tempfile.mkstemp(prefix='.extrato-ofx-', suffix='.tmp', dir=destination.parent)
        temporary = Path(name)
        with os.fdopen(descriptor, 'w', encoding='utf-8', newline='') as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, destination)
    except FileExistsError:
        raise OfxError('output_exists', 'O destino já existe. Escolha um arquivo novo; nada foi sobrescrito.') from None
    except (OSError, UnicodeError, ValueError, TypeError):
        raise OfxError('output_write', 'Não foi possível publicar um relatório novo com link exclusivo.') from None
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def _silence_broken_stdout():
    # Prevent interpreter shutdown from retrying a failed buffered flush and
    # replacing the documented error status with Python's exit status 120.
    try:
        descriptor = sys.stdout.fileno()
        sink = os.open(os.devnull, os.O_WRONLY)
        try:
            os.dup2(sink, descriptor)
        finally:
            os.close(sink)
    except (OSError, ValueError, AttributeError):
        pass


def _write_stdout(text=None):
    try:
        if text is not None:
            binary = getattr(sys.stdout, 'buffer', None)
            if binary is None:
                # Embedded callers may provide a text-only stream such as
                # StringIO. Native stdout exposes the byte-preserving buffer.
                sys.stdout.write(text)
            else:
                # Bypass platform newline translation and terminal encoding:
                # JSON/Markdown use LF; CSV already contains exact CRLF bytes.
                sys.stdout.flush()
                payload = text.encode('utf-8')
                if binary.write(payload) != len(payload):
                    raise OSError('Incomplete stdout write')
        sys.stdout.flush()
    except (OSError, UnicodeError, ValueError):
        _silence_broken_stdout()
        raise OfxError('output_write', 'Não foi possível escrever o relatório na saída padrão.') from None


def _diagnostic(message):
    try:
        sys.stderr.write(message + '\n')
        sys.stderr.flush()
    except (OSError, UnicodeError, ValueError):
        pass


_ERROR_MESSAGES = {
    'input_type': 'A origem deve ser arquivo regular; use - para stdin.',
    'input_size': 'A entrada excede o limite de bytes.',
    'input_encoding': 'A codificação não pertence ao perfil documentado.',
    'input_read': 'Não foi possível ler uma entrada OFX dentro do limite.',
    'output_exists': 'O destino já existe. Escolha um arquivo novo; nada foi sobrescrito.',
    'output_write': 'Não foi possível escrever ou publicar o relatório.',
    'incomplete_csv': 'O perfil não cobre todo o arquivo. Confira o JSON ou permita explicitamente CSV incompleto.',
    'output_size': 'O relatório excede o limite de bytes.',
    'invalid_report': 'O resultado não tem a forma documentada do relatório.',
}


def main(argv=None):
    try:
        try:
            args = _parser().parse_args(argv)
        except SystemExit as stop:
            _write_stdout()
            return 0 if stop.code == 0 else 3
        except (TypeError, ValueError):
            raise _UsageError('Argumentos inválidos. Use --help para consultar o formato aceito.') from None
        if (not args.file or '\x00' in args.file
                or (args.output is not None and (not args.output or '\x00' in args.output))):
            raise _UsageError('A origem e o destino devem ser textos não vazios e válidos.')
        try:
            limits = Limits(**{key: getattr(args, key) for key in asdict(Limits())})
        except OfxError:
            raise _UsageError('Orçamentos inválidos. Consulte os intervalos permitidos na documentação.') from None
        report = parse_ofx(_read_input(args.file, limits), limits=limits)
        if args.format == 'csv':
            text = to_csv(report, limits=limits, allow_incomplete=args.allow_incomplete_csv)
        else:
            text = {'json': to_json, 'markdown': to_markdown}[args.format](report, limits=limits)
        if args.output is None:
            _write_stdout(text)
        else:
            _publish_new(Path(args.output), text)
        return 0 if report['status'] == 'ok' else 2
    except _UsageError as error:
        _diagnostic('Erro de uso: ' + str(error))
        return 3
    except OfxError as error:
        code = error.code if type(error.code) is str and re.fullmatch(r'[a-z_]{1,64}', error.code) else 'profile'
        _diagnostic('Erro operacional (' + code + '): ' +
                    _ERROR_MESSAGES.get(code, 'A entrada não atende ao perfil documentado.'))
        return 3
    except (OSError, UnicodeError, ValueError):
        _silence_broken_stdout()
        _diagnostic('Erro operacional (io): Não foi possível ler ou escrever os dados.')
        return 3


if __name__ == '__main__':
    raise SystemExit(main())
