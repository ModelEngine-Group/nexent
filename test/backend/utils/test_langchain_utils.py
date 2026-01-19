from unittest.mock import MagicMock

from backend.utils.langchain_utils import discover_langchain_modules, _is_langchain_tool


class TestLangchainUtils:
    """Tests for backend.utils.langchain_utils functions"""

    def test_is_langchain_tool_with_base_tool(self, mocker):
        """Returns True for objects that are instances of BaseTool"""
        # Mock BaseTool class and create instance
        mock_base_tool_class = MagicMock()
        mock_tool_instance = MagicMock()

        mocker.patch('langchain_core.tools.BaseTool',
                     mock_base_tool_class)
        mocker.patch('backend.utils.langchain_utils.isinstance',
                     return_value=True)

        result = _is_langchain_tool(mock_tool_instance)
        assert result is True

    def test_is_langchain_tool_with_non_base_tool(self, mocker):
        """Returns False for objects that are not instances of BaseTool"""
        mock_base_tool_class = MagicMock()

        mocker.patch('langchain_core.tools.BaseTool',
                     mock_base_tool_class)
        mocker.patch('backend.utils.langchain_utils.isinstance',
                     return_value=False)

        result = _is_langchain_tool("not a tool")
        assert result is False

    def test_discover_langchain_modules_success(self, mocker):
        """测试成功发现LangChain工具的情况"""
        # 创建一个临时目录结构
        mocker.patch('os.path.isdir', return_value=True)
        mocker.patch('os.listdir', return_value=[
            'tool1.py', 'tool2.py', '__init__.py', 'not_a_py_file.txt'])
        mock_spec = mocker.patch('importlib.util.spec_from_file_location')
        mock_module_from_spec = mocker.patch('importlib.util.module_from_spec')

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
        result = discover_langchain_modules(filter_func=mock_filter)

        # 验证loader.exec_module被调用
        mock_loader1.exec_module.assert_called_once_with(mock_module_obj1)
        mock_loader2.exec_module.assert_called_once_with(mock_module_obj2)

        # 验证结果
        assert len(result) == 2
        discovered_objs = [obj for (obj, _) in result]
        assert mock_tool1 in discovered_objs
        assert mock_tool2 in discovered_objs

    def test_discover_langchain_modules_directory_not_found(self, mocker):
        """测试目录不存在的情况"""
        mocker.patch('os.path.isdir', return_value=False)
        result = discover_langchain_modules(directory="non_existent_dir")
        assert result == []

    def test_discover_langchain_modules_module_exception(self, mocker, mock_logger):
        """测试处理模块异常的情况"""
        mocker.patch('os.path.isdir', return_value=True)
        mocker.patch('os.listdir', return_value=['error_module.py'])
        mock_spec = mocker.patch('importlib.util.spec_from_file_location')
        mocker.patch('backend.utils.langchain_utils.logger', mock_logger)

        # 设置spec_from_file_location抛出异常
        mock_spec.side_effect = Exception("Module error")

        # 执行函数 - 应该捕获异常并继续
        result = discover_langchain_modules()

        # 验证结果为空列表
        assert result == []
        # 验证错误被记录
        assert mock_logger.error.called
        # 验证错误消息包含预期内容
        mock_logger.error.assert_called_with(
            "Error processing module error_module.py: Module error")

    def test_discover_langchain_modules_spec_loader_none(self, mocker, mock_logger):
        """测试spec或loader为None的情况"""
        mocker.patch('os.path.isdir', return_value=True)
        mocker.patch('os.listdir', return_value=['invalid_module.py'])
        mocker.patch('importlib.util.spec_from_file_location',
                     return_value=None)
        mocker.patch('backend.utils.langchain_utils.logger', mock_logger)

        # 执行函数
        result = discover_langchain_modules()

        # 验证结果为空列表
        assert result == []
        # 验证警告被记录
        assert mock_logger.warning.called
        # 验证警告消息包含预期内容 - 检查是否包含文件名
        actual_call = mock_logger.warning.call_args[0][0]
        assert "Failed to load spec for" in actual_call
        assert "invalid_module.py" in actual_call

    def test_discover_langchain_modules_custom_filter(self, mocker):
        """测试使用自定义过滤函数的情况"""
        mocker.patch('os.path.isdir', return_value=True)
        mocker.patch('os.listdir', return_value=['tool.py'])
        mock_spec = mocker.patch('importlib.util.spec_from_file_location')
        mock_module_from_spec = mocker.patch('importlib.util.module_from_spec')

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
        result = discover_langchain_modules(filter_func=custom_filter)

        # 验证loader.exec_module被调用
        mock_loader.exec_module.assert_called_once_with(mock_module_obj)

        # 验证结果 - 应该只有一个对象通过过滤
        assert len(result) == 1
        assert result[0][0] == obj_pass
