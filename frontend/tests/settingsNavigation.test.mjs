import test from 'node:test'
import assert from 'node:assert/strict'
import {configurationTabs,settingsTab,isConfigurationTab} from '../src/ui/settingsNavigation.ts'
test('super administrator settings retain configuration and operation tabs',()=>{
 for(const tab of [...configurationTabs,'backups','audit'])assert.equal(settingsTab('super_admin',tab),tab)
 assert.equal(settingsTab('super_admin',undefined),'brand')
})
test('administrator retains audit access without exposing backup or settings configuration',()=>{
 for(const tab of [...configurationTabs,'backups',undefined,['backups']])assert.equal(settingsTab('admin',tab),'audit')
 assert.equal(settingsTab('admin','audit'),'audit')
})
test('ordinary users have no administrator settings tabs',()=>{
 for(const role of ['user',undefined])for(const tab of ['audit','backups','brand'])assert.equal(settingsTab(role,tab),'')
})
test('operation tabs cannot enter the configuration save flow',()=>{
 assert.equal(isConfigurationTab('audit'),false);assert.equal(isConfigurationTab('backups'),false)
 assert.equal(isConfigurationTab('brand'),true)
})
