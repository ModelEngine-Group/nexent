# from langchain_core.tools import tool, StructuredTool
# from typing import Annotated
# from pydantic import BaseModel, Field
#
#
# @tool
# def add(a: int, b: int) -> int:
#     """
#     Calculate the sum of two numbers.
#     """
#     return a+b
#
# @tool
# def multiply(
#         a: Annotated[int, "scale factor"],
#         b: Annotated[int, "scale factor"],
# ) -> int:
#     """
#     Calculate the product of two integers.
#     """
#     return a * b
#
# @tool(parse_docstring=True)
# def subtraction(a: int, b: int) -> int:
#     """
#     Calculate the difference between two numbers.
#
#     Args:
#     a (int): The first number.
#     b (int): The second number.
#
#     Returns:
#     int: The difference between a and b.
#     """
#     return a-b
#
#
# class DivisionInput(BaseModel):
#     num1: int = Field(description="first number")
#     num2: int = Field(description="second number")
#
# @tool("division", args_schema=DivisionInput)
# def division(num1: int, num2: int) -> int:
#     """Return the quotient of two numbers."""
#     return num1//num2
#
#
# class ExponentiationInput(BaseModel):
#     num: int = Field(description="first number")
#     power: int = Field(description="second number")
#
#
# def exponentiation_func(num: int, power: int) -> int:
#     """Calculate the power of a number"""
#     return num**power
#
#
# exponentiation = StructuredTool.from_function(
#     func=exponentiation_func,
#     name="exponentiation",
#     description="Calculate the power of a number",
#     args_schema=ExponentiationInput,
#     return_direct=True,
#     # coroutine= ... <- you can specify an async method if desired as well
# )
