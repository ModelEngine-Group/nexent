import unittest
import sys
import os
from unittest.mock import MagicMock, patch

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', '..', '..')))

# 模拟主要依赖
sys.modules['langchain_core.tools'] = MagicMock()
sys.modules['consts'] = MagicMock()
sys.modules['consts.model'] = MagicMock()

# 模拟logger
logger_mock = MagicMock()


class TestLangchainUtils(unittest.TestCase):
    """测试langchain_utils模块的函数"""

    def setUp(self):
        """每个测试方法前的设置"""
        # 导入原始函数
        from backend.utils.langchain_utils import discover_langchain_modules, _is_langchain_tool
        self.discover_langchain_modules = discover_langchain_modules
        self._is_langchain_tool = _is_langchain_tool

    def test_is_langchain_tool(self):
        """测试_is_langchain_tool函数"""
        # 创建一个BaseTool实例的模拟
        mock_tool = MagicMock()

        # 模拟isinstance返回值
        with patch('backend.utils.langchain_utils.isinstance', return_value=True):
            result = self._is_langchain_tool(mock_tool)
            self.assertTrue(result)

        # 测试非BaseTool对象
        with patch('backend.utils.langchain_utils.isinstance', return_value=False):
            result = self._is_langchain_tool("not a tool")
            self.assertFalse(result)

    def test_discover_langchain_modules_success(self):
        """测试成功发现LangChain工具的情况"""
        # 创建一个临时目录结构
        with patch('os.path.isdir', return_value=True), \
                patch('os.listdir', return_value=['tool1.py', 'tool2.py', '__init__.py', 'not_a_py_file.txt']), \
                patch('importlib.util.spec_from_file_location') as mock_spec, \
                patch('importlib.util.module_from_spec') as mock_module_from_spec:

            # 创建模拟工具对象
            mock_tool1 = MagicMock(name="tool1")
            mock_tool2 = MagicMock(name="tool2")

            # 设置模拟module
            mock_module_obj1 = MagicMock()
            mock_module_obj1.tool_obj1 = mock_tool1

            mock_module_obj2 = MagicMock()
            mock_module_obj2.tool_obj2 = mock_tool2

            mock_module_from_spec.side_effect = [
                mock_module_obj1, mock_module_obj2]

            # 设置模拟spec和loader
            mock_spec_obj1 = MagicMock()
            mock_spec_obj2 = MagicMock()
            mock_spec.side_effect = [mock_spec_obj1, mock_spec_obj2]

            mock_loader1 = MagicMock()
            mock_loader2 = MagicMock()
            mock_spec_obj1.loader = mock_loader1
            mock_spec_obj2.loader = mock_loader2

            # 设置过滤函数始终返回True
            def mock_filter(obj):
                return obj is mock_tool1 or obj is mock_tool2

            # 执行函数
            result = self.discover_langchain_modules(filter_func=mock_filter)

            # 验证loader.exec_module被调用
            mock_loader1.exec_module.assert_called_once_with(mock_module_obj1)
            mock_loader2.exec_module.assert_called_once_with(mock_module_obj2)

            # 验证结果
            self.assertEqual(len(result), 2)
            discovered_objs = [obj for (obj, _) in result]
            self.assertIn(mock_tool1, discovered_objs)
            self.assertIn(mock_tool2, discovered_objs)

    def test_discover_langchain_modules_directory_not_found(self):
        """测试目录不存在的情况"""
        with patch('os.path.isdir', return_value=False):
            result = self.discover_langchain_modules(
                directory="non_existent_dir")
            self.assertEqual(result, [])

    def test_discover_langchain_modules_module_exception(self):
        """测试处理模块异常的情况"""
        with patch('os.path.isdir', return_value=True), \
                patch('os.listdir', return_value=['error_module.py']), \
                patch('importlib.util.spec_from_file_location') as mock_spec, \
                patch('backend.utils.langchain_utils.logger', logger_mock):

            # 设置spec_from_file_location抛出异常
            mock_spec.side_effect = Exception("Module error")

            # 执行函数 - 应该捕获异常并继续
            result = self.discover_langchain_modules()

            # 验证结果为空列表
            self.assertEqual(result, [])
            # 验证错误被记录
            self.assertTrue(logger_mock.error.called)
            # 验证错误消息包含预期内容
            logger_mock.error.assert_called_with(
                "Error processing module error_module.py: Module error")

    def test_discover_langchain_modules_spec_loader_none(self):
        """测试spec或loader为None的情况"""
        with patch('os.path.isdir', return_value=True), \
                patch('os.listdir', return_value=['invalid_module.py']), \
                patch('importlib.util.spec_from_file_location', return_value=None), \
                patch('backend.utils.langchain_utils.logger', logger_mock):

            # 执行函数
            result = self.discover_langchain_modules()

            # 验证结果为空列表
            self.assertEqual(result, [])
            # 验证警告被记录
            self.assertTrue(logger_mock.warning.called)
            # 验证警告消息包含预期内容 - 检查是否包含文件名
            actual_call = logger_mock.warning.call_args[0][0]
            self.assertIn("Failed to load spec for", actual_call)
            self.assertIn("invalid_module.py", actual_call)

    def test_discover_langchain_modules_custom_filter(self):
        """测试使用自定义过滤函数的情况"""
        with patch('os.path.isdir', return_value=True), \
                patch('os.listdir', return_value=['tool.py']), \
                patch('importlib.util.spec_from_file_location') as mock_spec, \
                patch('importlib.util.module_from_spec') as mock_module_from_spec:

            # 创建两个对象，一个通过过滤，一个不通过
            obj_pass = MagicMock(name="pass_object")
            obj_fail = MagicMock(name="fail_object")

            # 设置模拟module，使其包含我们的两个测试对象
            mock_module_obj = MagicMock()
            mock_module_obj.obj_pass = obj_pass
            mock_module_obj.obj_fail = obj_fail
            mock_module_from_spec.return_value = mock_module_obj

            # 设置模拟spec和loader
            mock_spec_obj = MagicMock()
            mock_spec.return_value = mock_spec_obj
            mock_loader = MagicMock()
            mock_spec_obj.loader = mock_loader

            # 自定义过滤函数，只接受obj_pass
            def custom_filter(obj):
                return obj is obj_pass

            # 执行函数
            result = self.discover_langchain_modules(filter_func=custom_filter)

            # 验证loader.exec_module被调用
            mock_loader.exec_module.assert_called_once_with(mock_module_obj)

            # 验证结果 - 应该只有一个对象通过过滤
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0][0], obj_pass)


if __name__ == "__main__":
    unittest.main()
