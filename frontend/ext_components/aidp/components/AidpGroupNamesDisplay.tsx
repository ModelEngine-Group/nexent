"use client";

import React from "react";
import { useTranslation } from "react-i18next";
import { Popover } from "antd";

const MAX_VISIBLE_GROUPS = 2;

interface AidpGroupNamesDisplayProps {
  groupNames: string[];
}

const AidpGroupNamesDisplay = ({ groupNames }: AidpGroupNamesDisplayProps) => {
  const { t } = useTranslation();
  const visibleGroups = groupNames.slice(0, MAX_VISIBLE_GROUPS);
  const remainingCount = Math.max(0, groupNames.length - visibleGroups.length);

  if (groupNames.length === 0) return null;

  return (
    <div
      data-testid="aidp-group-names"
      className="flex min-w-0 flex-nowrap items-center gap-1 overflow-hidden whitespace-nowrap"
    >
      {visibleGroups.map((groupName, index) => (
        <React.Fragment key={`${groupName}-${index}`}>
          {index > 0 && (
            <span aria-hidden="true" className="shrink-0">
              ·
            </span>
          )}
          <span title={groupName} className="min-w-0 flex-1 truncate">
            {groupName}
          </span>
        </React.Fragment>
      ))}
      {remainingCount > 0 && (
        <Popover
          trigger="click"
          placement="bottomLeft"
          title={t("aidpKnowledge.detailGroups", { count: groupNames.length })}
          content={
            <div className="max-h-60 w-64 max-w-[70vw] overflow-y-auto pr-1">
              <ul className="m-0 list-none space-y-1 p-0">
                {groupNames.map((groupName, index) => (
                  <li
                    key={`${groupName}-${index}`}
                    className="px-1 py-1 text-sm leading-5 text-gray-700 break-words"
                  >
                    {groupName}
                  </li>
                ))}
              </ul>
            </div>
          }
        >
          <button
            type="button"
            aria-label={`${t("aidpKnowledge.detailAllowedGroups")} +${remainingCount}`}
            className="shrink-0 rounded px-1 text-xs leading-5 text-blue-600 hover:bg-blue-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-500"
          >
            +{remainingCount}
          </button>
        </Popover>
      )}
    </div>
  );
};

export default AidpGroupNamesDisplay;
