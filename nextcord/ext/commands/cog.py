"""
The MIT License (MIT)

Copyright (c) 2015-present Rapptz

Permission is hereby granted, free of charge, to any person obtaining a
copy of this software and associated documentation files (the "Software"),
to deal in the Software without restriction, including without limitation
the rights to use, copy, modify, merge, publish, distribute, sublicense,
and/or sell copies of the Software, and to permit persons to whom the
Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS
OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
DEALINGS IN THE SOFTWARE.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Dict, Generator, List, Tuple, Type, TypeVar

import nextcord.utils
from nextcord._cog import _cog_special_method
from nextcord.cog import Cog as _Cog, CogMeta as _CogMeta

from ._types import _BaseCommand

if TYPE_CHECKING:
    from .bot import BotBase
    from .context import Context
    from .core import Command

__all__ = (
    "CogMeta",
    "Cog",
)

CogT = TypeVar("CogT", bound="Cog")
FuncT = TypeVar("FuncT", bound=Callable[..., Any])

MISSING: Any = nextcord.utils.MISSING


class CogMeta(_CogMeta):
    """The custom metaclass for Command Cogs.

    This class inherits from :class:`nextcord.CogMeta`.

    Attributes
    ----------
    command_attrs: :class:`dict`
        A list of attributes to apply to every command inside this cog. The dictionary
        is passed into the :class:`Command` options at ``__init__``.
        If you specify attributes inside the command attribute in the class, it will
        override the one specified inside this attribute. For example:

        .. code-block:: python3

            class MyCog(commands.Cog, command_attrs=dict(hidden=True)):
                @commands.command()
                async def foo(self, ctx):
                    pass # hidden -> True

                @commands.command(hidden=False)
                async def bar(self, ctx):
                    pass # hidden -> False
    """

    __cog_settings__: Dict[str, Any]
    __cog_commands__: List[Command]

    def __new__(cls: Type[CogMeta], *args: Any, **kwargs: Any) -> CogMeta:
        name, bases, attrs = args
        attrs["__cog_settings__"] = kwargs.pop("command_attrs", {})
        attrs["__cog_commands__"] = []
        new_cls = super().__new__(cls, name, bases, attrs, **kwargs)

        commands = {}
        no_bot_cog = (
            "Commands or listeners must not start with cog_ or bot_ (in method {0.__name__}.{1})"
        )

        for base in reversed(new_cls.__mro__):
            for elem, value in base.__dict__.items():
                if elem in commands:
                    del commands[elem]

                is_static_method = isinstance(value, staticmethod)
                if is_static_method:
                    value = value.__func__
                if isinstance(value, _BaseCommand):
                    if is_static_method:
                        raise TypeError(
                            f"Command in method {base}.{elem!r} must not be staticmethod."
                        )
                    if elem.startswith(("cog_", "bot_")):
                        raise TypeError(no_bot_cog.format(base, elem))
                    commands[elem] = value

        new_cls.__cog_commands__ = list(commands.values())
        return new_cls

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args)

    @classmethod
    def qualified_name(cls) -> str:
        return cls.__cog_name__


class Cog(_Cog, metaclass=CogMeta):
    """A base class that adds support for prefixed commands.

    This class inherits from :class:`nextcord.Cog` and uses the :class:`.CogMeta`
    metaclass. More information on them can be found on the
    :ref:`ext_commands_cogs` page.
    """

    __cog_name__: str
    __cog_settings__: Dict[str, Any]
    __cog_commands__: List[Command]
    __cog_listeners__: List[Tuple[str, str]]

    def __new__(cls: Type[CogT], *args: Any, **kwargs: Any) -> CogT:
        # For issue 426, we need to store a copy of the command objects
        # since we modify them to inject `self` to them.
        # To do this, we need to interfere with the Cog creation process.
        self = super().__new__(cls)
        cmd_attrs = cls.__cog_settings__

        # Either update the command with the cog provided defaults or copy it.
        # r.e type ignore, type-checker complains about overriding a ClassVar
        self.__cog_commands__ = tuple(c._update_copy(cmd_attrs) for c in cls.__cog_commands__)

        lookup = {
            cmd.qualified_name: cmd
            for cmd in self.__cog_commands__
            # pyright cannot read class annotations i guess
        }

        # Update the Command instances dynamically as well
        for command in self.__cog_commands__:
            setattr(self, command.callback.__name__, command)
            parent = command.parent
            if parent is not None:
                # Get the latest parent reference
                parent = lookup[parent.qualified_name]  # type: ignore

                # Update our parent's reference to our self
                parent.remove_command(command.name)  # type: ignore
                parent.add_command(command)  # type: ignore

        return self

    def get_commands(self) -> List[Command]:
        r"""
        Returns
        -------
        List[:class:`.Command`]
            A :class:`list` of :class:`.Command`\s that are
            defined inside this cog.

            .. note::

                This does not include subcommands.
        """
        return [c for c in self.__cog_commands__ if c.parent is None]

    @property
    def qualified_name(self) -> str:
        """:class:`str`: Returns the cog's specified name, not the class name."""
        return self.__cog_name__

    @property
    def description(self) -> str:
        """:class:`str`: Returns the cog's description, typically the cleaned docstring."""
        return self.__cog_description__

    @description.setter
    def description(self, description: str) -> None:
        self.__cog_description__ = description

    def walk_commands(self) -> Generator[Command, None, None]:
        """An iterator that recursively walks through this cog's commands and subcommands.

        Yields
        ------
        Union[:class:`.Command`, :class:`.Group`]
            A command or group from the cog.
        """
        from .core import GroupMixin

        for command in self.__cog_commands__:
            if command.parent is None:
                yield command
                if isinstance(command, GroupMixin):
                    yield from command.walk_commands()

    def has_error_handler(self) -> bool:
        """:class:`bool`: Checks whether the cog has an error handler.

        .. versionadded:: 1.7
        """
        return not hasattr(self.cog_command_error.__func__, "__cog_special_method__")

    @_cog_special_method
    def cog_unload(self) -> None:
        """A special method that is called when the cog gets removed.

        This function **cannot** be a coroutine. It must be a regular
        function.

        Subclasses must replace this if they want special unloading behaviour.
        """
        pass

    @_cog_special_method
    def bot_check_once(self, ctx: Context) -> bool:
        """A special method that registers as a :meth:`.Bot.check_once`
        check.

        This function **can** be a coroutine and must take a sole parameter,
        ``ctx``, to represent the :class:`.Context`.
        """
        return True

    @_cog_special_method
    def bot_check(self, ctx: Context) -> bool:
        """A special method that registers as a :meth:`.Bot.check`
        check.

        This function **can** be a coroutine and must take a sole parameter,
        ``ctx``, to represent the :class:`.Context`.
        """
        return True

    @_cog_special_method
    def cog_check(self, ctx: Context) -> bool:
        """A special method that registers as a :func:`~nextcord.ext.commands.check`
        for every command and subcommand in this cog.

        This function **can** be a coroutine and must take a sole parameter,
        ``ctx``, to represent the :class:`.Context`.
        """
        return True

    @_cog_special_method
    async def cog_command_error(self, ctx: Context, error: Exception) -> None:
        """A special method that is called whenever an error
        is dispatched inside this cog.

        This is similar to :func:`.on_command_error` except only applying
        to the commands inside this cog.

        This **must** be a coroutine.

        .. note::

            This is only called for prefix commands.

        Parameters
        ----------
        ctx: :class:`.Context`
            The invocation context where the error happened.
        error: :class:`CommandError`
            The error that happened.
        """
        pass

    @_cog_special_method
    async def cog_before_invoke(self, ctx: Context) -> None:
        """A special method that acts as a cog local pre-invoke hook.

        This is similar to :meth:`.Command.before_invoke`.

        This **must** be a coroutine.

        Parameters
        ----------
        ctx: :class:`.Context`
            The invocation context.
        """
        pass

    @_cog_special_method
    async def cog_after_invoke(self, ctx: Context) -> None:
        """A special method that acts as a cog local post-invoke hook.

        This is similar to :meth:`.Command.after_invoke`.

        This **must** be a coroutine.

        Parameters
        ----------
        ctx: :class:`.Context`
            The invocation context.
        """
        pass

    def _inject(self: CogT, bot: BotBase) -> CogT:
        cls = self.__class__

        # realistically, the only thing that can cause loading errors
        # is essentially just the command loading, which raises if there are
        # duplicates. When this condition is met, we want to undo all what
        # we've added so far for some form of atomic loading.
        for index, command in enumerate(self.__cog_commands__):
            command.cog = self
            if command.parent is None:
                try:
                    bot.add_command(command)
                except Exception as e:
                    # undo our additions
                    for to_undo in self.__cog_commands__[:index]:
                        if to_undo.parent is None:
                            bot.remove_command(to_undo.name)
                    raise e

        # check if we're overriding the default
        if cls.bot_check is not Cog.bot_check:
            bot.add_check(self.bot_check)

        if cls.bot_check_once is not Cog.bot_check_once:
            bot.add_check(self.bot_check_once, call_once=True)

        # while Bot.add_listener can raise if it's not a coroutine,
        # this precondition is already met by the listener decorator
        # already, thus this should never raise.
        # Outside of, memory errors and the like...
        for name, method_name in self.__cog_listeners__:
            bot.add_listener(getattr(self, method_name), name)

        return self

    def _eject(self, bot: BotBase) -> None:
        cls = self.__class__

        try:
            for command in self.__cog_commands__:
                if command.parent is None:
                    bot.remove_command(command.name)

            for _, method_name in self.__cog_listeners__:
                bot.remove_listener(getattr(self, method_name))

            if cls.bot_check is not Cog.bot_check:
                bot.remove_check(self.bot_check)

            if cls.bot_check_once is not Cog.bot_check_once:
                bot.remove_check(self.bot_check_once, call_once=True)
        finally:
            try:
                self.cog_unload()
            except Exception:
                pass
