# -*- coding: utf-8 -*-
"""The event filter expression parser filter classes."""

from __future__ import unicode_literals

import abc
import logging
import re

from plaso.filters import helpers
from plaso.formatters import manager as formatters_manager
from plaso.formatters import mediator as formatters_mediator
from plaso.lib import errors
from plaso.lib import py2to3


class Filter(object):
  """Filter interface.

  Attributes:
    args (list[object]): arguments provided to the filter.
  """

  def __init__(self, arguments=None):
    """Initializes a filter.

    Implementations expanders are provided by subclassing ValueExpander.

    Args:
      arguments (Optional[object]): arguments.
    """
    logging.debug('Adding {0!s}'.format(arguments))

    super(Filter, self).__init__()
    self.args = arguments or []

  @abc.abstractmethod
  def Matches(self, event):
    """Determines if the event matches the filter.

    Args:
      event (EventObject): event to compare against the filter.

    Returns:
      bool: True if the event matches the filter, False otherwise.
    """


class AndFilter(Filter):
  """A filter that performs a boolean AND on the arguments.

  Note that if no conditions are passed, all objects will pass.
  """

  def Matches(self, event):
    """Determines if the event matches the filter.

    Args:
      event (EventObject): event to compare against the filter.

    Returns:
      bool: True if the event matches the filter, False otherwise.
    """
    for sub_filter in self.args:
      if not sub_filter.Matches(event):
        return False
    return True


class OrFilter(Filter):
  """A filter that performs a boolean OR on the arguments.

  Note that if no conditions are passed, all objects will pass.
  """

  def Matches(self, event):
    """Determines if the event matches the filter.

    Args:
      event (EventObject): event to compare against the filter.

    Returns:
      bool: True if the event matches the filter, False otherwise.
    """
    if not self.args:
      return True

    for sub_filter in self.args:
      if sub_filter.Matches(event):
        return True
    return False


class Operator(Filter):
  """Interface for filters that represent operators."""

  @abc.abstractmethod
  def Matches(self, event):
    """Determines if the event matches the filter.

    Args:
      event (EventObject): event to compare against the filter.

    Returns:
      bool: True if the event matches the filter, False otherwise.
    """


class IdentityFilter(Operator):
  """A filter which always evaluates to True."""

  def Matches(self, event):
    """Determines if the event matches the filter.

    Args:
      event (EventObject): event to compare against the filter.

    Returns:
      bool: True if the event matches the filter, False otherwise.
    """
    return True


class BinaryOperator(Operator):
  """Interface for binary operators.

  Attributes:
    left_operand (object): left hand operand.
    right_operand (object): right hand operand.
  """

  def __init__(self, arguments=None, **kwargs):
    """Initializes a binary operator.

    Args:
      arguments (Optional[object]): operands of the filter.

    Raises:
      InvalidNumberOfOperands: if the number of operands provided is not
          supported.
    """
    if len(arguments) != 2:
      raise errors.InvalidNumberOfOperands((
          '{0:s} only supports 2 operands, provided were {1:d} '
          'operands.').format(self.__class__.__name__, len(arguments)))

    super(BinaryOperator, self).__init__(arguments=arguments, **kwargs)
    self.left_operand = arguments[0]
    self.right_operand = arguments[1]

  @abc.abstractmethod
  def Matches(self, event):
    """Determines if the event matches the filter.

    Args:
      event (EventObject): event to compare against the filter.

    Returns:
      bool: True if the event matches the filter, False otherwise.
    """


class GenericBinaryOperator(BinaryOperator):
  """Shared functionality for common binary operators."""

  _OBJECT_PATH_SEPARATOR = '.'

  def __init__(self, arguments=None, **kwargs):
    """Initializes a generic binary operator.

    Args:
      arguments (Optional[object]): operands of the filter.
    """
    super(GenericBinaryOperator, self).__init__(arguments=arguments, **kwargs)
    self._bool_value = True

  @abc.abstractmethod
  def _CompareValue(self, event_value, filter_value):
    """Compares two values with the operator.

    Args:
      event_value (object): value retrieved from the event.
      filter_value (object): value defined by the filter.

    Returns:
      bool: True if the values match according to the operator, False otherwise.
    """

  def _GetMessage(self, event):
    """Retrieves a formatted message string.

    Args:
      event (EventObject): event.

    Returns:
      str: formatted message string.
    """
    # TODO: move this somewhere where the mediator can be instantiated once.
    formatter_mediator = formatters_mediator.FormatterMediator()

    result = ''
    try:
      result, _ = formatters_manager.FormattersManager.GetMessageStrings(
          formatter_mediator, event)
    except KeyError as exception:
      logging.warning(
          'Unable to correctly assemble event with error: {0!s}'.format(
              exception))

    return result

  def _GetSources(self, event):
    """Retrieves a formatted source strings.

    Args:
      event (EventObject): event.

    Returns:
      tuple(str, str): short and long source string.
    """
    try:
      # TODO: refactor to pass event and event_data as separate arguments.
      source_short, source_long = (
          formatters_manager.FormattersManager.GetSourceStrings(
              event, event))
    except KeyError as exception:
      logging.warning(
          'Unable to correctly assemble event with error: {0!s}'.format(
              exception))

    return source_short, source_long

  def _GetValue(self, event, attribute_name):
    """Retrieves the value of a specific event attribute.

    Args:
      event (EventObject): event to retrieve the value from.
      attribute_name (str): name of the attribute to retrieve the value from.

    Returns:
      object: attribute value or None if not available.
    """
    if attribute_name == 'message':
      return self._GetMessage(event)

    if attribute_name in ('source', 'source_short'):
      source_short, _ = self._GetSources(event)
      return source_short

    if attribute_name in ('source_long', 'sourcetype'):
      _, source_long = self._GetSources(event)
      return source_long

    attribute_value = getattr(event, attribute_name, None)
    if attribute_value:
      if attribute_name == 'tag':
        return attribute_value.labels

      if isinstance(attribute_value, dict):
        return helpers.DictObject(attribute_value)

    return attribute_value

  def _GetValueByPath(self, event, path):
    """Retrieves the value of a specific event attribute given an object path.

    Given an object path such as ["pathspec", "inode"] it returns the value
    event.pathspec.inode.

    Args:
      event (EventObject): event to retrieve the value from.
      path (list[str]): object path to traverse, that contains the attribute
          names.

    Returns:
      object: attribute value or None if not available.
    """
    if isinstance(path, py2to3.STRING_TYPES):
      path = path.split(self._OBJECT_PATH_SEPARATOR)

    attribute_name = path[0].lower()
    attribute_value = self._GetValue(event, attribute_name)

    if attribute_value is None:
      return None

    if len(path) == 1 or isinstance(attribute_value, dict):
      return attribute_value

    return self._GetValueByPath(attribute_value, path[1:])

  def FlipBool(self):
    """Negates the internal boolean value attribute."""
    logging.debug('Negative matching.')
    self._bool_value = not self._bool_value

  def Matches(self, event):
    """Determines if the event matches the filter.

    Args:
      event (EventObject): event to compare against the filter.

    Returns:
      bool: True if the event matches the filter, False otherwise.
    """
    object_path = self.left_operand.split('.')
    value = self._GetValueByPath(event, object_path)

    if value and self._CompareValue(value, self.right_operand):
      return self._bool_value
    return not self._bool_value


class EqualsOperator(GenericBinaryOperator):
  """Equals (==) operator."""

  def _CompareValue(self, event_value, filter_value):
    """Compares if two values are equal.

    Args:
      event_value (object): value retrieved from the event.
      filter_value (object): value defined by the filter.

    Returns:
      bool: True if the values are equal, False otherwise.
    """
    return event_value == filter_value


class NotEqualsOperator(GenericBinaryOperator):
  """Not equals (!=) operator."""

  def _CompareValue(self, event_value, filter_value):
    """Compares if two values are not equal.

    Args:
      event_value (object): value retrieved from the event.
      filter_value (object): value defined by the filter.

    Returns:
      bool: True if the values are not equal, False otherwise.
    """
    return event_value != filter_value


class LessThanOperator(GenericBinaryOperator):
  """Less than (<) operator."""

  def _CompareValue(self, event_value, filter_value):
    """Compares if the event value is less than the second.

    Args:
      event_value (object): value retrieved from the event.
      filter_value (object): value defined by the filter.

    Returns:
      bool: True if the event value is less than the second, False otherwise.
    """
    return event_value < filter_value


class LessEqualOperator(GenericBinaryOperator):
  """Less than or equals (<=) operator."""

  def _CompareValue(self, event_value, filter_value):
    """Compares if the event value is less than or equals the second.

    Args:
      event_value (object): value retrieved from the event.
      filter_value (object): value defined by the filter.

    Returns:
      bool: True if the event value is than or equals the second, False
          otherwise.
    """
    return event_value <= filter_value


class GreaterThanOperator(GenericBinaryOperator):
  """Greater than (>) operator."""

  def _CompareValue(self, event_value, filter_value):
    """Compares if the event value is greater than the second.

    Args:
      event_value (object): value retrieved from the event.
      filter_value (object): value defined by the filter.

    Returns:
      bool: True if the event value is greater than the second, False otherwise.
    """
    return event_value > filter_value


class GreaterEqualOperator(GenericBinaryOperator):
  """Greater than or equals (>=) operator."""

  def _CompareValue(self, event_value, filter_value):
    """Compares if the event value is greater than or equals the second.

    Args:
      event_value (object): value retrieved from the event.
      filter_value (object): value defined by the filter.

    Returns:
      bool: True if the event value is greater than or equals the second, False
          otherwise.
    """
    return event_value >= filter_value


class Contains(GenericBinaryOperator):
  """Operator to determine if a value contains another value."""

  def _CompareValue(self, event_value, filter_value):
    """Compares if the second value is part of the first.

    Note that this method will do a case insensitive comparion if the first
    value is a string.

    Args:
      event_value (object): value retrieved from the event.
      filter_value (object): value defined by the filter.

    Returns:
      bool: True if the second value is part of the first, False otherwise.
    """
    try:
      if isinstance(event_value, py2to3.STRING_TYPES):
        return filter_value.lower() in event_value.lower()

      return filter_value in event_value
    except (AttributeError, TypeError):
      return False


# TODO: Change to an N-ary Operator?
class InSet(GenericBinaryOperator):
  """Operator to determine if a value is part of another value."""

  def _CompareValue(self, event_value, filter_value):
    """Compares if the event value is part of the second.

    Note that this method will do a case insensitive string comparion if
    the event value is a string.

    Args:
      event_value (object): value retrieved from the event.
      filter_value (object): value defined by the filter.

    Returns:
      bool: True if the event value is part of the second, False otherwise.
    """
    if event_value in filter_value:
      return True

    # event_value might be an iterable
    # first we need to skip strings or we'll do silly things
    # pylint: disable=consider-merging-isinstance
    if (isinstance(event_value, py2to3.STRING_TYPES) or
        isinstance(event_value, bytes)):
      return False

    try:
      for value in event_value:
        if value not in filter_value:
          return False
      return True
    except TypeError:
      return False


# TODO: is GenericBinaryOperator the most suitable super class here?
# Would BinaryOperator be a better fit?
class Regexp(GenericBinaryOperator):
  """Operator to determine if a value matches a regular expression.

  Attributes:
    compiled_re (???): compiled regular expression.
  """

  def __init__(self, arguments=None, **kwargs):
    """Initializes a regular expression operator.

    This operator uses case senstive comparision.

    Args:
      arguments (Optional[object]): operands of the filter.

    Raises:
      ValueError: if the regular expression is malformed.
    """
    super(Regexp, self).__init__(arguments=arguments, **kwargs)

    # Note that right_operand is not necessarily a string.
    logging.debug('Compiled: {0!s}'.format(self.right_operand))

    try:
      expression = helpers.GetUnicodeString(self.right_operand)
      compiled_re = re.compile(expression, re.DOTALL)
    except re.error:
      raise ValueError('Regular expression "{0!s}" is malformed.'.format(
          self.right_operand))

    self.compiled_re = compiled_re

  def _CompareValue(self, event_value, filter_value):
    """Compares if the event value matches a regular expression.

    Args:
      event_value (object): value retrieved from the event.
      filter_value (object): value defined by the filter.

    Returns:
      bool: True if the event value matches the regular expression, False
          otherwise.
    """
    try:
      string_value = helpers.GetUnicodeString(event_value)
      if self.compiled_re.search(string_value):
        return True
    except TypeError:
      pass

    return False


class RegexpInsensitive(Regexp):
  """Operator to determine if a value matches a regular expression."""

  def __init__(self, arguments=None, **kwargs):
    """Initializes a regular expression operator.

    This operator uses case insenstive comparision.

    Args:
      arguments (Optional[object]): operands of the filter.

    Raises:
      ValueError: if the regular expression is malformed.
    """
    super(RegexpInsensitive, self).__init__(arguments=arguments, **kwargs)

    # Note that right_operand is not necessarily a string.
    logging.debug('Compiled: {0!s}'.format(self.right_operand))

    try:
      expression = helpers.GetUnicodeString(self.right_operand)
      compiled_re = re.compile(expression, re.I | re.DOTALL)
    except re.error:
      raise ValueError('Regular expression "{0!s}" is malformed.'.format(
          self.right_operand))

    self.compiled_re = compiled_re
