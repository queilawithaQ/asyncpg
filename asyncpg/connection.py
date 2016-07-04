from . import introspection
from . import prepared_stmt
from . import transaction


class Connection:

    __slots__ = ('_protocol', '_transport', '_loop', '_types_stmt',
                 '_type_by_name_stmt', '_top_xact', '_uid')

    def __init__(self, protocol, transport, loop):
        self._protocol = protocol
        self._transport = transport
        self._loop = loop
        self._types_stmt = None
        self._type_by_name_stmt = None
        self._top_xact = None
        self._uid = 0

    def get_settings(self):
        return self._protocol.get_settings()

    def transaction(self, *, isolation='read_committed', readonly=False,
                    deferrable=False):

        return transaction.Transaction(self, isolation, readonly, deferrable)

    async def execute(self, script):
        await self._protocol.query(script)

    async def prepare(self, query):
        state = await self._protocol.prepare(None, query)

        ready = state._init_types()
        if ready is not True:
            if self._types_stmt is None:
                self._types_stmt = await self.prepare(
                    introspection.INTRO_LOOKUP_TYPES)

            types = await self._types_stmt.get_list(list(ready))
            self._protocol.get_settings().register_data_types(types)

        return prepared_stmt.PreparedStatement(self, state)

    async def set_type_codec(self, typename, *,
                             schema='public', encoder, decoder, binary=False):
        """Set an encoder/decoder pair for the specified data type

        :param typename:  Name of the data type the codec is for.
        :param schema:  Schema name of the data type the codec is for
                        (defaults to 'public')
        :param encoder:  Callable accepting a single argument and returning
                         a string or a bytes object (if `binary` is True).
        :param decoder:  Callable accepting a single string or bytes argument
                         and returning a decoded object.
        :param binary:  Specifies whether the codec is able to handle binary
                        data.  If ``False`` (the default), the data is
                        expected to be encoded/decoded in text.
        """
        if self._type_by_name_stmt is None:
            self._type_by_name_stmt = await self.prepare(
                introspection.TYPE_BY_NAME)

        typeinfo = await self._type_by_name_stmt.get_first_row(
            typename, schema)
        if not typeinfo:
            raise ValueError('unknown type: {}.{}'.format(schema, typename))

        oid = typeinfo['oid']
        if typeinfo['kind'] != b'b' or typeinfo['elemtype']:
            raise ValueError(
                'cannot use custom codec on non-scalar type {}.{}'.format(
                    schema, typename))

        self._protocol.get_settings().add_python_codec(
            oid, typename, schema, 'scalar',
            encoder, decoder, binary)

    async def alias_type(self, typename, *, schema='public', alias_to):
        if self._type_by_name_stmt is None:
            self._type_by_name_stmt = await self.prepare(
                introspection.TYPE_BY_NAME)

        typeinfo = await self._type_by_name_stmt.get_first_row(
            typename, schema)
        if not typeinfo:
            raise ValueError('unknown type: {}.{}'.format(schema, typename))

        oid = typeinfo['oid']
        if typeinfo['kind'] != b'b' or typeinfo['elemtype']:
            raise ValueError(
                'cannot alias non-scalar type {}.{}'.format(
                    schema, typename))

        self._protocol.get_settings().add_codec_alias(
            oid, typename, schema, 'scalar', alias_to)

    def close(self):
        self._transport.close()

    def _get_unique_id(self):
        self._uid += 1
        return 'id{}'.format(self._uid)